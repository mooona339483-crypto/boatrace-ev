import json
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

            HAVING
                snapshot_2t IS NOT NULL
                AND snapshot_3t IS NOT NULL

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
                venue_name,
                category,
                deadline,
                raw_html
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
            float(row["odds"])
        for row in rows
    }


def active_boats_from_odds(
    odds_map,
):
    active = set()

    for selection in odds_map:
        parts = selection.split("-")

        for value in parts:
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
        return "EXISTS", 0

    odds_map = load_odds(
        snapshot_id,
        bet_type,
    )

    active_numbers = (
        active_boats_from_odds(
            odds_map
        )
    )

    if len(active_numbers) not in (
        5,
        6,
    ):
        raise ValueError(
            "Invalid active boat count"
        )

    boats = build_boats(
        racelist,
        preview,
        active_numbers,
    )

    if (
        len(boats)
        != len(active_numbers)
    ):
        raise ValueError(
            "Incomplete active boat data"
        )

    selections = build_payload(
        boats,
        odds_map,
        bet_type,
    )

    save_shadow(
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

    return (
        "SAVED",
        len(selections),
    )


def record_ready_predictions():
    init_db()

    rows = get_checkpoint_pairs()

    saved = 0
    skipped = 0
    errors = 0

    for row in rows:

        race_id = row[
            "race_id"
        ]

        checkpoint = row[
            "checkpoint_minutes"
        ]

        if checkpoint not in CHECKPOINTS:
            continue

        race_info = get_race_info(
            row["race_date"],
            row["venue_code"],
            row["race_no"],
        )

        if race_info is None:
            skipped += 1
            continue

        try:
            racelist = parse_racelist(
                race_info[
                    "raw_html"
                ]
            )

            preview = fetch_preview(
                row["race_date"],
                row["venue_code"],
                row["race_no"],
            )

            if (
                preview["status"]
                != "READY"
            ):
                skipped += 1

                print(
                    "SHADOW_SKIP",
                    race_id,
                    "checkpoint=",
                    checkpoint,
                    preview["reason"],
                    flush=True,
                )

                continue

            results = []

            configs = (
                (
                    "2T",
                    row["snapshot_2t"],
                    row["minutes_2t"],
                    row["captured_2t"],
                ),
                (
                    "3T",
                    row["snapshot_3t"],
                    row["minutes_3t"],
                    row["captured_3t"],
                ),
            )

            for (
                bet_type,
                snapshot_id,
                actual_minutes,
                captured_at,
            ) in configs:

                try:
                    status, count = record_one(
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

            if any(
                status == "SAVED"
                for (
                    _,
                    status,
                    _,
                ) in results
            ):
                print(
                    "SHADOW_RECORDED",
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
                race_id,
                "checkpoint=",
                checkpoint,
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
