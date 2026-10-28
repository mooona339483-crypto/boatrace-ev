import json
import math
from itertools import permutations
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from boatcast_preview import fetch_preview
from combined_racer_parser import parse_racelist
from probability_model import (
    Boat,
    predict_probabilities,
)


JST = ZoneInfo("Asia/Tokyo")

DB = os.environ.get(
    "DB_PATH",
    "/data/boatrace_ev.sqlite3",
)

MODEL_VERSION = "heuristic-v1"

CHECKPOINTS = (
    2,
    1,
)


def connect():
    con = sqlite3.connect(
        DB,
        timeout=30,
    )

    con.row_factory = sqlite3.Row

    return con


def now_jst():
    return datetime.now(
        JST
    )


def init_db():
    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS shadow_prediction_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                race_id TEXT NOT NULL,
                race_date TEXT NOT NULL,
                venue_code TEXT NOT NULL,
                race_no INTEGER NOT NULL,
                race_category TEXT NOT NULL,
                deadline TEXT,

                bet_type TEXT NOT NULL,

                checkpoint_minutes INTEGER NOT NULL,
                actual_minutes REAL NOT NULL,

                odds_snapshot_id INTEGER NOT NULL,
                odds_captured_at TEXT NOT NULL,

                model_version TEXT NOT NULL,
                model_verified INTEGER NOT NULL,

                selections_json TEXT NOT NULL,
                selection_count INTEGER NOT NULL,

                status TEXT NOT NULL,
                recorded_at TEXT NOT NULL,

                UNIQUE(
                    race_id,
                    bet_type,
                    checkpoint_minutes,
                    model_version
                )
            )
            """
        )

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_shadow_race
            ON shadow_prediction_records (
                race_id,
                bet_type,
                checkpoint_minutes
            )
            """
        )


def init_issue_db():
    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS shadow_data_issues (
                race_id TEXT NOT NULL,
                checkpoint_minutes INTEGER NOT NULL,
                bet_type TEXT NOT NULL,
                boat_number INTEGER NOT NULL,
                missing_field TEXT NOT NULL,
                reason TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                observation_scope TEXT NOT NULL,

                PRIMARY KEY (
                    race_id,
                    checkpoint_minutes,
                    bet_type,
                    boat_number,
                    missing_field
                )
            )
            """
        )


def get_checkpoint_pairs():
    with connect() as con:
        rows = con.execute(
            """
            SELECT
                race_id,
                race_date,
                venue_code,
                race_no,
                checkpoint_minutes,

                MAX(
                    CASE
                        WHEN bet_type='2T'
                        THEN snapshot_id
                    END
                ) AS snapshot_2t,

                MAX(
                    CASE
                        WHEN bet_type='3T'
                        THEN snapshot_id
                    END
                ) AS snapshot_3t,

                MAX(
                    CASE
                        WHEN bet_type='2T'
                        THEN actual_minutes
                    END
                ) AS minutes_2t,

                MAX(
                    CASE
                        WHEN bet_type='3T'
                        THEN actual_minutes
                    END
                ) AS minutes_3t,

                MAX(
                    CASE
                        WHEN bet_type='2T'
                        THEN captured_at
                    END
                ) AS captured_2t,

                MAX(
                    CASE
                        WHEN bet_type='3T'
                        THEN captured_at
                    END
                ) AS captured_3t

            FROM odds_checkpoints

            WHERE checkpoint_minutes
                IN (1, 2)

            GROUP BY
                race_id,
                race_date,
                venue_code,
                race_no,
                checkpoint_minutes

            ORDER BY
                race_date,
                race_no,
                checkpoint_minutes DESC
            """
        ).fetchall()

    return rows


def already_recorded(
    race_id,
    bet_type,
    checkpoint,
):
    with connect() as con:
        row = con.execute(
            """
            SELECT 1
            FROM shadow_prediction_records
            WHERE race_id=?
              AND bet_type=?
              AND checkpoint_minutes=?
              AND model_version=?
            LIMIT 1
            """,
            (
                race_id,
                bet_type,
                checkpoint,
                MODEL_VERSION,
            ),
        ).fetchone()

    return row is not None


def get_race_info(
    race_date,
    venue_code,
    race_no,
):
    with connect() as con:
        row = con.execute(
            """
            SELECT
                race_date,
                venue_name,
                category,
                deadline,
                raw_html,
                fetched_at
            FROM race_pages
            WHERE race_date=?
              AND venue_code=?
              AND race_no=?
              AND category != 'female'
            ORDER BY fetched_at DESC
            LIMIT 1
            """,
            (
                race_date,
                venue_code,
                race_no,
            ),
        ).fetchone()

    return row


def load_odds(
    snapshot_id,
    bet_type,
):
    with connect() as con:
        rows = con.execute(
            """
            SELECT
                selection,
                odds
            FROM mapped_odds
            WHERE snapshot_id=?
              AND bet_type=?
            ORDER BY selection
            """,
            (
                snapshot_id,
                bet_type,
            ),
        ).fetchall()

    return {
        row["selection"]:
            row["odds"]
        for row in rows
    }


def active_boats_from_odds(
    odds_map,
):
    active = set()

    for selection in odds_map:
        for value in selection.split("-"):
            try:
                number = int(value)
            except ValueError:
                continue

            if 1 <= number <= 6:
                active.add(number)

    if len(active) not in (
        5,
        6,
    ):
        return []

    return sorted(active)


def expected_count(
    boat_count,
    bet_type,
):
    if bet_type == "2T":
        return (
            boat_count
            * (boat_count - 1)
        )

    if bet_type == "3T":
        return (
            boat_count
            * (boat_count - 1)
            * (boat_count - 2)
        )

    raise ValueError(
        "Invalid bet type"
    )


def build_boats(
    racelist,
    preview,
    active_numbers,
):
    exhibition = preview[
        "exhibition"
    ]

    courses = preview[
        "courses"
    ]

    active_numbers = sorted(
        active_numbers
    )

    if len(active_numbers) not in (
        5,
        6,
    ):
        return []

    for number in active_numbers:
        if (
            number not in racelist
            or number not in exhibition
            or number not in courses
        ):
            return []

    course_values = [
        courses[number]
        for number in active_numbers
    ]

    if (
        len(set(course_values))
        != len(course_values)
    ):
        return []

    boats = []

    for number in active_numbers:
        data = racelist[number]

        boats.append(
            Boat(
                number=number,
                racer_win_rate=data[
                    "racer_win_rate"
                ],
                motor_2rate=data[
                    "motor_2rate"
                ],
                exhibition_time=(
                    exhibition[number]
                ),
                average_st=data[
                    "average_st"
                ],
                course=courses[
                    number
                ],
            )
        )

    return boats


def build_payload(
    boats,
    odds_map,
    bet_type,
):
    probabilities = (
        predict_probabilities(
            boats,
            bet_type,
        )
    )

    boat_count = len(
        boats
    )

    expected = expected_count(
        boat_count,
        bet_type,
    )

    if len(odds_map) != expected:
        raise ValueError(
            "Incomplete odds map"
        )

    if len(probabilities) != expected:
        raise ValueError(
            "Incomplete probability map"
        )

    if (
        set(probabilities)
        != set(odds_map)
    ):
        raise ValueError(
            "Odds/probability mismatch"
        )

    result = []

    for selection in sorted(
        probabilities
    ):
        probability = (
            probabilities[
                selection
            ]
        )

        odds = odds_map[
            selection
        ]

        ev = (
            probability
            * odds
            - 1
        )

        result.append(
            {
                "selection":
                    selection,
                "probability":
                    round(
                        probability,
                        8,
                    ),
                "odds":
                    round(
                        odds,
                        2,
                    ),
                "ev":
                    round(
                        ev,
                        6,
                    ),
            }
        )

    return result


def parse_timestamp(value):
    if not isinstance(
        value,
        str,
    ):
        return None

    try:
        parsed = (
            datetime.fromisoformat(
                value
            )
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return None

    return parsed


def deadline_datetime(
    race_date,
    value,
):
    parsed = parse_timestamp(
        value
    )

    if parsed is not None:
        return parsed

    if (
        not isinstance(
            value,
            str,
        )
        or not isinstance(
            race_date,
            str,
        )
    ):
        return None

    try:
        return datetime.strptime(
            f"{race_date} {value}",
            "%Y%m%d %H:%M",
        ).replace(
            tzinfo=JST
        )

    except ValueError:
        return None


def finite_number(value):
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            (int, float),
        )
    ):
        return False

    try:
        return math.isfinite(
            value
        )

    except OverflowError:
        return False


def as_mapping(value):
    return (
        value
        if isinstance(
            value,
            dict,
        )
        else {}
    )


def selection_numbers(
    selection,
    bet_type,
):
    if not isinstance(
        selection,
        str,
    ):
        return ()

    parts = selection.split("-")

    count = (
        2
        if bet_type == "2T"
        else 3
    )

    if (
        len(parts)
        != count
        or len(
            set(parts)
        )
        != count
        or any(
            part not in {
                "1",
                "2",
                "3",
                "4",
                "5",
                "6",
            }
            for part in parts
        )
    ):
        return ()

    return tuple(
        int(part)
        for part in parts
    )


def observed_boats(
    odds_map,
    bet_type,
    racelist,
    preview,
):
    """Prefer a consistent preview roster; odds must not hide a whole boat.

    Racelist may still contain a withdrawn sixth boat, so only use it as a
    fallback when exhibition/course rosters are incomplete or inconsistent.
    Conflicting observed boat numbers are retained for diagnosis, not dropped.
    """
    numbers = set()

    for selection in odds_map:
        numbers.update(
            selection_numbers(
                selection,
                bet_type,
            )
        )

    preview = as_mapping(
        preview
    )

    exhibition = {
        number
        for number in as_mapping(
            preview.get(
                "exhibition"
            )
        )
        if (
            type(number) is int
            and 1 <= number <= 6
        )
    }

    courses = {
        number
        for number in as_mapping(
            preview.get(
                "courses"
            )
        )
        if (
            type(number) is int
            and 1 <= number <= 6
        )
    }

    numbers.update(
        exhibition | courses
    )

    if (
        exhibition != courses
        or len(exhibition)
        not in (5, 6)
    ):
        numbers.update(
            number
            for number in as_mapping(
                racelist
            )
            if (
                type(number) is int
                and 1 <= number <= 6
            )
        )

    return sorted(
        numbers
    )


def diagnose_inputs(
    racelist,
    preview,
    odds_map,
    bet_type,
    snapshot_id,
):
    """Describe observed inputs, not the original historical failure cause.

    boat=0 means a boat cannot be identified. Preview boat rosters supplement
    the odds universe; incomplete preview falls back to the racelist.
    """
    issues = set()

    racers = as_mapping(
        racelist
    )

    preview = as_mapping(
        preview
    )

    exhibition = as_mapping(
        preview.get(
            "exhibition"
        )
    )

    courses = as_mapping(
        preview.get(
            "courses"
        )
    )

    numbers = observed_boats(
        odds_map,
        bet_type,
        racers,
        preview,
    )

    targets = (
        numbers
        or [0]
    )

    def issue(
        number,
        field,
        reason,
    ):
        issues.add(
            (
                number,
                field,
                reason,
            )
        )

    if len(numbers) not in (
        5,
        6,
    ):
        issue(
            0,
            "odds",
            "active_boats_unresolved",
        )

    for number in targets:
        data = racers.get(
            number
        )

        if not isinstance(
            data,
            dict,
        ):
            issue(
                number,
                "racelist",
                "boat_row_missing_or_invalid",
            )

            data = {}

        for field in (
            "racer_win_rate",
            "motor_2rate",
            "average_st",
        ):
            value = data.get(
                field
            )

            if not finite_number(
                value
            ):
                issue(
                    number,
                    field,
                    (
                        "missing"
                        if value is None
                        else "invalid_number"
                    ),
                )

        value = exhibition.get(
            number
        )

        if not finite_number(
            value
        ):
            issue(
                number,
                "exhibition_time",
                (
                    "missing"
                    if value is None
                    else "invalid_number"
                ),
            )

        course = courses.get(
            number
        )

        if (
            not finite_number(
                course
            )
            or course
            not in range(
                1,
                7,
            )
        ):
            issue(
                number,
                "course",
                (
                    "missing"
                    if course is None
                    else "invalid_course"
                ),
            )

        elif (
            sum(
                courses.get(
                    candidate
                )
                == course
                for candidate
                in numbers
            )
            > 1
        ):
            issue(
                number,
                "course",
                "duplicate_course",
            )

    if (
        snapshot_id is None
        or not odds_map
    ):
        for number in targets:
            issue(
                number,
                "odds",
                (
                    "snapshot_missing"
                    if snapshot_id is None
                    else "empty_snapshot"
                ),
            )

    else:
        for (
            selection,
            odds,
        ) in odds_map.items():

            participants = (
                selection_numbers(
                    selection,
                    bet_type,
                )
            )

            if not participants:
                issue(
                    0,
                    "odds",
                    "invalid_selection",
                )

            elif (
                not finite_number(
                    odds
                )
                or odds < 1
            ):
                for number in participants:
                    issue(
                        number,
                        "odds",
                        "invalid_number",
                    )

        if len(numbers) in (
            5,
            6,
        ):
            odds_boats = set()

            for selection in odds_map:
                odds_boats.update(
                    selection_numbers(
                        selection,
                        bet_type,
                    )
                )

            missing_whole = (
                set(numbers)
                - odds_boats
            )

            for number in missing_whole:
                issue(
                    number,
                    "odds",
                    "boat_missing_from_odds",
                )

            count = (
                2
                if bet_type == "2T"
                else 3
            )

            for combination in permutations(
                numbers,
                count,
            ):
                key = "-".join(
                    map(
                        str,
                        combination,
                    )
                )

                if (
                    key not in odds_map
                    and not (
                        missing_whole
                        .intersection(
                            combination
                        )
                    )
                ):
                    issue(
                        0,
                        "odds",
                        "selection_missing",
                    )

    return sorted(
        issues
    )


def prediction_time_valid(
    race_info,
    captured_at,
    actual_minutes,
):
    if race_info is None:
        return False

    deadline = (
        deadline_datetime(
            race_info[
                "race_date"
            ],
            race_info[
                "deadline"
            ],
        )
    )

    captured = parse_timestamp(
        captured_at
    )

    fetched = parse_timestamp(
        race_info[
            "fetched_at"
        ]
    )

    now = now_jst()

    return (
        deadline is not None
        and captured is not None
        and fetched is not None
        and finite_number(
            actual_minutes
        )
        and actual_minutes > 0
        and captured <= now
        and fetched <= now
        and captured < deadline
        and fetched < deadline
        and now < deadline
    )


def record_issues(
    row,
    bet_type,
    issues,
    observation_scope,
):
    observed_at = (
        now_jst()
        .isoformat()
    )

    inserted = []

    with connect() as con:
        for (
            number,
            field,
            reason,
        ) in issues:

            cur = con.execute(
                """
                INSERT OR IGNORE INTO shadow_data_issues (
                    race_id,
                    checkpoint_minutes,
                    bet_type,
                    boat_number,
                    missing_field,
                    reason,
                    observed_at,
                    observation_scope
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row[
                        "race_id"
                    ],
                    row[
                        "checkpoint_minutes"
                    ],
                    bet_type,
                    number,
                    field,
                    reason,
                    observed_at,
                    observation_scope,
                ),
            )

            if cur.rowcount:
                inserted.append(
                    (
                        number,
                        field,
                        reason,
                    )
                )

    for (
        number,
        field,
        reason,
    ) in inserted:

        print(
            "DATA_ISSUE",
            f"race={row['race_id']}",
            f"checkpoint={row['checkpoint_minutes']}",
            f"bet={bet_type}",
            f"boat={number}",
            f"missing={field}",
            f"reason={reason}",
            f"observed_at={observed_at}",
            f"scope={observation_scope}",
            flush=True,
        )


def save_shadow(
    *,
    race_id,
    race_date,
    venue_code,
    race_no,
    race_category,
    deadline,
    bet_type,
    checkpoint,
    actual_minutes,
    snapshot_id,
    odds_captured_at,
    selections,
):
    payload = json.dumps(
        selections,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )

    with connect() as con:
        con.execute(
            "BEGIN IMMEDIATE"
        )

        parsed_deadline = (
            deadline_datetime(
                race_date,
                deadline,
            )
        )

        if (
            parsed_deadline
            is None
            or now_jst()
            >= parsed_deadline
        ):
            return False

        con.execute(
            """
            INSERT OR IGNORE INTO shadow_prediction_records (
                race_id,
                race_date,
                venue_code,
                race_no,
                race_category,
                deadline,
                bet_type,
                checkpoint_minutes,
                actual_minutes,
                odds_snapshot_id,
                odds_captured_at,
                model_version,
                model_verified,
                selections_json,
                selection_count,
                status,
                recorded_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, 0, ?, ?,
                'SHADOW_RECORDED',
                ?
            )
            """,
            (
                race_id,
                race_date,
                venue_code,
                race_no,
                race_category,
                deadline,
                bet_type,
                checkpoint,
                actual_minutes,
                snapshot_id,
                odds_captured_at,
                MODEL_VERSION,
                payload,
                len(selections),
                now_jst().isoformat(),
            ),
        )

    return True


def record_one(
    *,
    row,
    race_info,
    racelist,
    preview,
    bet_type,
    snapshot_id,
    actual_minutes,
    captured_at,
):
    race_id = row[
        "race_id"
    ]

    checkpoint = row[
        "checkpoint_minutes"
    ]

    if already_recorded(
        race_id,
        bet_type,
        checkpoint,
    ):
        return (
            "EXISTS",
            0,
        )

    odds_map = (
        load_odds(
            snapshot_id,
            bet_type,
        )
        if snapshot_id
        is not None
        else {}
    )

    issues = diagnose_inputs(
        racelist,
        preview,
        odds_map,
        bet_type,
        snapshot_id,
    )

    eligible_time = (
        race_info is not None
        and prediction_time_valid(
            race_info,
            captured_at,
            actual_minutes,
        )
    )

    scope = (
        "pre_deadline_observation"
        if eligible_time
        else
        "diagnosis_only_current_observation"
    )

    record_issues(
        row,
        bet_type,
        issues,
        scope,
    )

    if not eligible_time:
        return (
            "SKIP_DIAGNOSTIC_ONLY_TIME",
            0,
        )

    if issues:
        return (
            "SKIP_INCOMPLETE_DATA",
            0,
        )

    if (
        as_mapping(
            preview
        ).get(
            "status"
        )
        != "READY"
    ):
        return (
            "SKIP_PREVIEW_NOT_READY",
            0,
        )

    active_numbers = (
        active_boats_from_odds(
            odds_map
        )
    )

    boats = build_boats(
        racelist,
        preview,
        active_numbers,
    )

    if (
        len(boats)
        != len(active_numbers)
        or len(boats)
        not in (
            5,
            6,
        )
    ):
        return (
            "SKIP_INCOMPLETE_DATA",
            0,
        )

    try:
        selections = (
            build_payload(
                boats,
                odds_map,
                bet_type,
            )
        )

    except (
        ValueError,
        TypeError,
        OverflowError,
    ):
        return (
            "SKIP_ODDS_MISMATCH",
            0,
        )

    if not prediction_time_valid(
        race_info,
        captured_at,
        actual_minutes,
    ):
        return (
            "SKIP_DIAGNOSTIC_ONLY_TIME",
            0,
        )

    saved = save_shadow(
        race_id=race_id,
        race_date=row[
            "race_date"
        ],
        venue_code=row[
            "venue_code"
        ],
        race_no=row[
            "race_no"
        ],
        race_category=(
            race_info[
                "category"
            ]
        ),
        deadline=(
            race_info[
                "deadline"
            ]
        ),
        bet_type=bet_type,
        checkpoint=checkpoint,
        actual_minutes=(
            actual_minutes
        ),
        snapshot_id=(
            snapshot_id
        ),
        odds_captured_at=(
            captured_at
        ),
        selections=(
            selections
        ),
    )

    if saved:
        return (
            "SAVED",
            len(selections),
        )

    return (
        "SKIP_DIAGNOSTIC_ONLY_TIME",
        0,
    )


def record_ready_predictions():
    init_db()
    init_issue_db()

    saved = 0
    skipped = 0
    errors = 0

    for row in get_checkpoint_pairs():

        try:
            race_id = row[
                "race_id"
            ]

            checkpoint = row[
                "checkpoint_minutes"
            ]

            if checkpoint not in CHECKPOINTS:
                continue

            configs = [
                (
                    bet_type,
                    row[
                        f"snapshot_{suffix}"
                    ],
                    row[
                        f"minutes_{suffix}"
                    ],
                    row[
                        f"captured_{suffix}"
                    ],
                )
                for (
                    bet_type,
                    suffix,
                ) in (
                    (
                        "2T",
                        "2t",
                    ),
                    (
                        "3T",
                        "3t",
                    ),
                )
                if not already_recorded(
                    race_id,
                    bet_type,
                    checkpoint,
                )
            ]

            if not configs:
                continue

            race_info = (
                get_race_info(
                    row[
                        "race_date"
                    ],
                    row[
                        "venue_code"
                    ],
                    row[
                        "race_no"
                    ],
                )
            )

            racelist = {}

            if race_info is not None:
                try:
                    racelist = (
                        parse_racelist(
                            race_info[
                                "raw_html"
                            ]
                        )
                    )

                except (
                    ValueError,
                    TypeError,
                    KeyError,
                    OverflowError,
                ):
                    pass

            try:
                preview = (
                    fetch_preview(
                        row[
                            "race_date"
                        ],
                        row[
                            "venue_code"
                        ],
                        row[
                            "race_no"
                        ],
                    )
                )

            except Exception as error:
                preview = {}

                print(
                    "SHADOW_PREVIEW_ERROR",
                    race_id,
                    type(error).__name__,
                    flush=True,
                )

            results = []

            for (
                bet_type,
                snapshot_id,
                actual_minutes,
                captured_at,
            ) in configs:

                try:
                    (
                        status,
                        count,
                    ) = record_one(
                        row=row,
                        race_info=(
                            race_info
                        ),
                        racelist=(
                            racelist
                        ),
                        preview=(
                            preview
                        ),
                        bet_type=(
                            bet_type
                        ),
                        snapshot_id=(
                            snapshot_id
                        ),
                        actual_minutes=(
                            actual_minutes
                        ),
                        captured_at=(
                            captured_at
                        ),
                    )

                    results.append(
                        (
                            bet_type,
                            status,
                            count,
                        )
                    )

                    if status == "SAVED":
                        saved += 1

                    elif status.startswith(
                        "SKIP"
                    ):
                        skipped += 1

                except Exception as error:
                    errors += 1

                    print(
                        "SHADOW_BET_ERROR",
                        race_id,
                        bet_type,
                        "checkpoint=",
                        checkpoint,
                        type(error).__name__,
                        str(error)[:160],
                        flush=True,
                    )

            if results:
                print(
                    "SHADOW_RESULT",
                    race_id,
                    "checkpoint=",
                    checkpoint,
                    "details=",
                    results,
                    "verified=",
                    False,
                    flush=True,
                )

        except Exception as error:
            errors += 1

            print(
                "SHADOW_ERROR",
                type(error).__name__,
                str(error)[:160],
                flush=True,
            )

    print(
        "SHADOW_DONE",
        "saved=",
        saved,
        "skipped=",
        skipped,
        "errors=",
        errors,
        "verified=",
        False,
        flush=True,
    )

    return {
        "saved":
            saved,
        "skipped":
            skipped,
        "errors":
            errors,
    }


if __name__ == "__main__":
    record_ready_predictions()
