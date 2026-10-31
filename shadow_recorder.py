import json
import math
import re
from itertools import permutations
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from boatcast_preview import fetch_preview
from combined_racer_parser import parse_racelist_diagnostic as parse_racelist
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

    # A diagnostic-only storage failure must not disable normal predictions.
    try:
        with connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS shadow_data_issues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    race_id TEXT NOT NULL,
                    checkpoint INTEGER NOT NULL,
                    bet_type TEXT NOT NULL,
                    boat_number INTEGER NOT NULL,
                    missing_field TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    observation_scope TEXT NOT NULL,
                    UNIQUE (race_id, checkpoint, bet_type, boat_number, missing_field)
                )
            """)
            issue_checkpoint_column(con)
    except sqlite3.Error as error:
        print("DATA_ISSUE_STORAGE_ERROR", "stage=init", type(error).__name__,
              str(error)[:160], flush=True)


def issue_checkpoint_column(con):
    """Recognize only the two known diagnostic schemas without migrating data.

    Returned identifiers come from this fixed allowlist, never from raw SQL
    supplied by a database row. Unknown constraints fail diagnostic storage
    only; the caller keeps normal prediction handling independent.
    """
    table = con.execute("SELECT type, sql FROM sqlite_master WHERE name=?",
                        ("shadow_data_issues",)).fetchone()
    if table is None or table[0] != "table":
        raise sqlite3.DatabaseError("unsupported diagnostic table")
    ddl = (table[1] or "").upper()
    if re.search(r"\b(?:CHECK|REFERENCES|COLLATE|DEFAULT|GENERATED|STRICT)\b"
                 r"|\bWITHOUT\s+ROWID\b|\bON\s+CONFLICT\b", ddl):
        raise sqlite3.DatabaseError("unsupported diagnostic constraints")
    info = {row[1]: row for row in con.execute(
        "SELECT * FROM pragma_table_xinfo(?)", ("shadow_data_issues",))}
    choices = [name for name in ("checkpoint", "checkpoint_minutes") if name in info]
    if len(choices) != 1:
        raise sqlite3.DatabaseError("ambiguous diagnostic checkpoint column")
    checkpoint_column = choices[0]
    fields = {"race_id", checkpoint_column, "bet_type", "boat_number",
              "missing_field", "reason", "observed_at", "observation_scope"}
    old_schema = checkpoint_column == "checkpoint_minutes"
    expected = fields if old_schema else fields | {"id"}
    if set(info) != expected:
        raise sqlite3.DatabaseError("incompatible diagnostic columns")
    for name in fields:
        row = info[name]
        kind = "INTEGER" if name in (checkpoint_column, "boat_number") else "TEXT"
        if row[2].upper() != kind or not row[3] or row[4] is not None or row[6]:
            raise sqlite3.DatabaseError("incompatible diagnostic column definition")
    key = ("race_id", checkpoint_column, "bet_type", "boat_number", "missing_field")
    primary = tuple(row[1] for row in sorted(info.values(), key=lambda row: row[5])
                    if row[5])
    if old_schema:
        if primary != key:
            raise sqlite3.DatabaseError("incompatible diagnostic primary key")
    else:
        identity = info["id"]
        if (primary != ("id",) or identity[2].upper() != "INTEGER"
                or identity[4] is not None or identity[6]):
            raise sqlite3.DatabaseError("incompatible diagnostic identity")
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
                   ("shadow_data_issues",)).fetchone():
        raise sqlite3.DatabaseError("unsupported diagnostic trigger")
    has_unique_key = False
    for index in con.execute("SELECT * FROM pragma_index_list(?)",
                             ("shadow_data_issues",)).fetchall():
        details = con.execute("SELECT * FROM pragma_index_xinfo(?)",
                              (index[1],)).fetchall()
        indexed = tuple(row[2] for row in details if row[5])
        standard = all(row[2] in fields and row[3] == 0 and row[4] == "BINARY"
                       for row in details if row[5])
        if index[2]:
            if index[4] or indexed != key or not standard:
                raise sqlite3.DatabaseError("unsupported diagnostic unique index")
            has_unique_key = True
        elif index[1] == "idx_shadow_data_issue_key":
            raise sqlite3.DatabaseError("incompatible named diagnostic index")
    if not has_unique_key:
        raise sqlite3.DatabaseError("missing diagnostic unique key")
    return checkpoint_column


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
            row["odds"]
        for row in rows
    }


def deadline_datetime(race_date, deadline):
    """Unknown or malformed deadlines fail closed."""
    try:
        return datetime.strptime(
            f"{race_date}{deadline}", "%Y%m%d%H:%M"
        ).replace(tzinfo=JST)
    except (TypeError, ValueError):
        return None


def before_deadline(race_date, deadline):
    cutoff = deadline_datetime(race_date, deadline)
    return cutoff is not None and now_jst() < cutoff


def prediction_before_deadline(race_date, deadline, captured_at, actual_minutes):
    """Both the odds capture and the current operation must precede cutoff."""
    cutoff = deadline_datetime(race_date, deadline)
    if (cutoff is None or not isinstance(captured_at, str)
            or not finite_number(actual_minutes) or actual_minutes <= 0):
        return False
    try:
        captured = datetime.fromisoformat(captured_at)
        if captured.tzinfo is None or captured.utcoffset() is None:
            return False
        if captured >= cutoff:
            return False
    except (TypeError, ValueError, OverflowError):
        return False
    return before_deadline(race_date, deadline)


def finite_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
        return False


def boat_keys(value):
    if not isinstance(value, dict):
        return set()
    return {n for n in value if type(n) is int and 1 <= n <= 6}


def selection_boats(selection, bet_type):
    if not isinstance(selection, str):
        return ()
    parts = selection.split("-")
    size = 2 if bet_type == "2T" else 3
    if (len(parts) != size or len(set(parts)) != size
            or any(p not in ("1", "2", "3", "4", "5", "6") for p in parts)):
        return ()
    return tuple(map(int, parts))


def observed_boats(odds_map, racelist, preview, bet_type):
    """Preview distinguishes cancelled boats from an odds feed missing a boat."""
    odds_boats = set()
    if isinstance(odds_map, dict):
        for selection in odds_map:
            odds_boats.update(selection_boats(selection, bet_type))
    preview = preview if isinstance(preview, dict) else {}
    exhibition = boat_keys(preview.get("exhibition"))
    courses = boat_keys(preview.get("courses"))
    if exhibition == courses and len(exhibition) in (5, 6):
        # A complete 5-boat preview must not be expanded by a stale 6-boat racelist.
        return sorted(odds_boats | exhibition)
    # Either source can positively identify a sixth boat, but incomplete or
    # disagreeing preview sources need the racelist as supplementary evidence.
    return sorted(odds_boats | exhibition | courses | boat_keys(racelist))


def diagnose_inputs(racelist, preview, odds_map, bet_type):
    numbers = observed_boats(odds_map, racelist, preview, bet_type)
    issues = {}

    def issue(number, field, reason):
        issues.setdefault((number, field), reason)

    racers = racelist if isinstance(racelist, dict) else {}
    preview = preview if isinstance(preview, dict) else {}
    exhibition = preview.get("exhibition")
    courses = preview.get("courses")
    exhibition = exhibition if isinstance(exhibition, dict) else {}
    courses = courses if isinstance(courses, dict) else {}
    if not numbers:
        issue(0, "racelist", "active_boats_unknown")
    for number in numbers:
        data = racers.get(number)
        if not isinstance(data, dict):
            issue(number, "racelist", "boat_missing_or_invalid")
            data = {}
        for field in ("racer_win_rate", "motor_2rate", "average_st"):
            value = data.get(field)
            if value is None:
                issue(number, field, "missing")
            elif not finite_number(value):
                issue(number, field, "invalid_number")
        value = exhibition.get(number)
        if value is None:
            issue(number, "exhibition_time", "missing")
        elif not finite_number(value):
            issue(number, "exhibition_time", "invalid_number")
        value = courses.get(number)
        if value is None:
            issue(number, "course", "missing")
        elif type(value) is not int or not 1 <= value <= 6:
            issue(number, "course", "invalid_course")
    for number in numbers:
        course = courses.get(number)
        if type(course) is int and sum(courses.get(n) == course for n in numbers) > 1:
            issue(number, "course", "duplicate_course")

    odds = odds_map if isinstance(odds_map, dict) else {}
    odds_boats = set()
    valid_keys = set()
    for selection, value in odds.items():
        participants = selection_boats(selection, bet_type)
        if not participants:
            issue(0, "odds", "invalid_selection")
            continue
        valid_keys.add(selection)
        odds_boats.update(participants)
        if not finite_number(value) or value <= 0:
            issue(0, "odds", "invalid_value")
    missing_boats = set(numbers) - odds_boats
    for number in sorted(missing_boats):
        issue(number, "odds", "boat_missing_from_odds")
    if not odds and not numbers:
        issue(0, "odds", "odds_missing")
    size = 2 if bet_type == "2T" else 3
    expected = {"-".join(map(str, selection)) for selection in permutations(numbers, size)}
    for selection in expected - valid_keys:
        # A whole missing boat already explains these combinations. Do not
        # blame the other, correctly represented participants.
        if not (set(selection_boats(selection, bet_type)) & missing_boats):
            issue(0, "odds", "selection_missing")
    if valid_keys - expected:
        issue(0, "odds", "unexpected_selection")
    return numbers, [(n, field, reason) for (n, field), reason in sorted(issues.items())]


def save_data_issues(race_id, checkpoint, bet_type, issues, observation_scope):
    """Store/log the first observation only; never overwrite prediction data.

    observed_at is the diagnostic observation time, not the checkpoint time.
    Post-deadline observations do not prove what was missing before deadline.
    """
    if not issues:
        return 0
    observed_at = now_jst().isoformat()
    inserted = []
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        checkpoint_column = issue_checkpoint_column(con)
        for number, field, reason in issues:
            exists = con.execute(f"""SELECT 1 FROM shadow_data_issues
                WHERE race_id=? AND {checkpoint_column}=? AND bet_type=?
                  AND boat_number=? AND missing_field=? LIMIT 1""",
                (race_id, checkpoint, bet_type, number, field)).fetchone()
            if exists:
                continue
            cursor = con.execute(f"""
                INSERT INTO shadow_data_issues
                    (race_id, {checkpoint_column}, bet_type, boat_number, missing_field,
                     reason, observed_at, observation_scope)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (race_id, checkpoint, bet_type, number, field, reason,
                  observed_at, observation_scope))
            if cursor.rowcount != 1:
                raise sqlite3.DatabaseError("diagnostic row was not inserted")
            inserted.append((number, field, reason))
    for number, field, reason in inserted:
        print("DATA_ISSUE", f"race_id={race_id}", f"checkpoint={checkpoint}",
              f"bet_type={bet_type}", f"boat_number={number}",
              f"missing_field={field}", f"reason={reason}",
              f"observed_at={observed_at}", f"observation_scope={observation_scope}",
              flush=True)
    return len(inserted)



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
        con.execute("BEGIN IMMEDIATE")
        if not prediction_before_deadline(
            race_date, deadline, odds_captured_at, actual_minutes
        ):
            return False
        cursor = con.execute(
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

    return bool(cursor.rowcount)


def record_one(*, row, race_info, racelist, preview, bet_type,
               snapshot_id, actual_minutes, captured_at):
    race_id = row["race_id"]
    checkpoint = row["checkpoint_minutes"]
    if already_recorded(race_id, bet_type, checkpoint):
        return "EXISTS", 0
    odds_map = load_odds(snapshot_id, bet_type) if snapshot_id is not None else {}
    numbers, issues = diagnose_inputs(racelist, preview, odds_map, bet_type)
    deadline = race_info["deadline"] if race_info is not None else None
    allowed = before_deadline(row["race_date"], deadline)
    scope = ("current_inputs_before_deadline" if allowed else
             "current_inputs_after_deadline_or_unknown")
    try:
        save_data_issues(race_id, checkpoint, bet_type, issues, scope)
    except sqlite3.Error as error:
        print("DATA_ISSUE_STORAGE_ERROR", f"race_id={race_id}",
              f"checkpoint={checkpoint}", f"bet_type={bet_type}",
              type(error).__name__, str(error)[:160], flush=True)
    # Recheck after fetching inputs/diagnostic persistence, before model work.
    if not prediction_before_deadline(
        row["race_date"], deadline, captured_at, actual_minutes
    ):
        return "SKIP_DEADLINE", 0
    if issues or len(numbers) not in (5, 6):
        return "SKIP_INCOMPLETE_DATA", 0
    if not isinstance(preview, dict) or preview.get("status") != "READY":
        return "SKIP_PREVIEW_NOT_READY", 0
    boats = build_boats(racelist, preview, numbers)
    try:
        selections = build_payload(boats, odds_map, bet_type)
    except (ValueError, TypeError, KeyError, OverflowError):
        return "SKIP_INVALID_DATA", 0
    # Model execution can cross the cutoff, even if input acquisition did not.
    if not prediction_before_deadline(
        row["race_date"], deadline, captured_at, actual_minutes
    ):
        return "SKIP_DEADLINE", 0
    saved = save_shadow(
        race_id=race_id, race_date=row["race_date"],
        venue_code=row["venue_code"], race_no=row["race_no"],
        race_category=race_info["category"], deadline=deadline,
        bet_type=bet_type, checkpoint=checkpoint,
        actual_minutes=actual_minutes, snapshot_id=snapshot_id,
        odds_captured_at=captured_at, selections=selections,
    )
    return ("SAVED", len(selections)) if saved else ("SKIP_NOT_INSERTED", 0)


def record_ready_predictions():
    init_db()
    saved = skipped = errors = 0
    for row in get_checkpoint_pairs():
        race_id = "unknown"
        checkpoint = None
        try:
            race_id = row["race_id"]
            checkpoint = row["checkpoint_minutes"]
            if checkpoint not in CHECKPOINTS:
                continue
            # Do not fetch again or diagnose an already recorded normal pair.
            if all(already_recorded(race_id, bet, checkpoint) for bet in ("2T", "3T")):
                continue
            race_info = get_race_info(row["race_date"], row["venue_code"], row["race_no"])
            try:
                racelist = parse_racelist(race_info["raw_html"]) if race_info else {}
            except (ValueError, TypeError, KeyError, AttributeError):
                racelist = {}
            # Do not spend HTTP time on rows that cannot make a new prediction.
            # Post-deadline/unknown-deadline diagnostics are intentionally omitted;
            # pre-deadline diagnostic handling and all later save guards remain.
            deadline = race_info["deadline"] if race_info is not None else None
            if not before_deadline(row["race_date"], deadline):
                skipped += sum(not already_recorded(race_id, bet, checkpoint)
                               for bet in ("2T", "3T"))
                print("SHADOW_PREVIEW_SKIPPED", race_id, "checkpoint=", checkpoint,
                      "reason=DEADLINE_PASSED_OR_UNKNOWN", "verified=", False,
                      flush=True)
                continue
            try:
                preview = fetch_preview(row["race_date"], row["venue_code"], row["race_no"])
            except Exception as error:
                preview = {}
                print("SHADOW_PREVIEW_ERROR", race_id, type(error).__name__, flush=True)
            # No prediction uses post-cutoff fetched data. record_one persists
            # only explicitly scoped diagnostics when already past deadline.
            results = []
            for bet_type, suffix in (("2T", "2t"), ("3T", "3t")):
                try:
                    status, count = record_one(
                        row=row, race_info=race_info, racelist=racelist,
                        preview=preview, bet_type=bet_type,
                        snapshot_id=row["snapshot_" + suffix],
                        actual_minutes=row["minutes_" + suffix],
                        captured_at=row["captured_" + suffix],
                    )
                    results.append((bet_type, status, count))
                    saved += status == "SAVED"
                    skipped += status.startswith("SKIP")
                except Exception as error:
                    errors += 1
                    print("SHADOW_BET_ERROR", race_id, bet_type,
                          "checkpoint=", checkpoint, type(error).__name__,
                          str(error)[:160], flush=True)
            if results:
                print("SHADOW_RESULT", race_id, "checkpoint=", checkpoint,
                      "details=", results, "verified=", False, flush=True)
        except Exception as error:
            errors += 1
            print("SHADOW_ERROR", race_id, "checkpoint=", checkpoint,
                  type(error).__name__, str(error)[:160], flush=True)
    print("SHADOW_DONE", "saved=", saved, "skipped=", skipped,
          "errors=", errors, "verified=", False, flush=True)
    return {"saved": saved, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    record_ready_predictions()
