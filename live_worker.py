import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from market_collector import (
    fetch,
    init_db as init_market_db,
)

from odds_mapper import (
    init_db as init_odds_db,
    map_2t,
    map_3t,
    save_odds,
)


JST = ZoneInfo("Asia/Tokyo")

DB = os.environ.get(
    "DB_PATH",
    "/data/boatrace_ev.sqlite3",
)

BASE = "https://www.boatrace.jp/owpc/pc/race"

POLL_SECONDS = 20

CHECKPOINTS = (
    5,
    2,
    1,
)

CHECKPOINT_TOLERANCE = 0.65

RESULT_INTERVAL_SECONDS = 300
BACKTEST_INTERVAL_SECONDS = 1800
SCHEDULE_RETRY_SECONDS = 1800


def connect():
    con = sqlite3.connect(
        DB,
        timeout=30,
    )

    con.row_factory = sqlite3.Row

    return con


def now_jst():
    return datetime.now(JST)


def today_string():
    return now_jst().strftime(
        "%Y%m%d"
    )


def make_race_id(
    race_date,
    venue_code,
    race_no,
):
    return (
        f"{race_date}-"
        f"{str(venue_code).zfill(2)}-"
        f"{int(race_no):02d}"
    )


def init_live_db():
    init_market_db()
    init_odds_db()

    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id TEXT NOT NULL,
                race_date TEXT NOT NULL,
                venue_code TEXT NOT NULL,
                race_no INTEGER NOT NULL,
                bet_type TEXT NOT NULL,
                checkpoint_minutes INTEGER NOT NULL,
                actual_minutes REAL NOT NULL,
                snapshot_id INTEGER NOT NULL,
                captured_at TEXT NOT NULL,

                UNIQUE(
                    race_id,
                    bet_type,
                    checkpoint_minutes
                )
            )
            """
        )

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_odds_checkpoint_race
            ON odds_checkpoints (
                race_date,
                venue_code,
                race_no,
                checkpoint_minutes
            )
            """
        )


def deadline_datetime(
    race_date,
    deadline,
):
    if not deadline:
        return None

    try:
        value = datetime.strptime(
            f"{race_date}{deadline}",
            "%Y%m%d%H:%M",
        )

    except ValueError:
        return None

    return value.replace(
        tzinfo=JST
    )


def get_today_races():
    race_date = today_string()

    with connect() as con:
        rows = con.execute(
            """
            SELECT
                venue_code,
                venue_name,
                race_no,
                category,
                deadline
            FROM race_pages
            WHERE race_date=?
              AND category != 'female'
            GROUP BY
                venue_code,
                venue_name,
                race_no,
                category,
                deadline
            ORDER BY
                venue_code,
                race_no
            """,
            (
                race_date,
            ),
        ).fetchall()

    return race_date, rows


def checkpoint_exists(
    race_id,
    bet_type,
    checkpoint,
):
    with connect() as con:
        row = con.execute(
            """
            SELECT 1
            FROM odds_checkpoints
            WHERE race_id=?
              AND bet_type=?
              AND checkpoint_minutes=?
            LIMIT 1
            """,
            (
                race_id,
                bet_type,
                checkpoint,
            ),
        ).fetchone()

    return row is not None


def nearest_checkpoint(
    minutes_to_deadline,
):
    candidates = sorted(
        (
            (
                abs(
                    minutes_to_deadline
                    - checkpoint
                ),
                checkpoint,
            )
            for checkpoint
            in CHECKPOINTS
        ),
        key=lambda item:
            item[0],
    )

    distance, checkpoint = (
        candidates[0]
    )

    if (
        distance
        > CHECKPOINT_TOLERANCE
    ):
        return None

    return checkpoint


def expected_count(
    odds_map,
    bet_type,
):
    active_boats = set()

    for selection in odds_map:
        active_boats.update(
            int(value)
            for value
            in selection.split("-")
        )

    boat_count = len(
        active_boats
    )

    if boat_count not in (
        5,
        6,
    ):
        return None

    if bet_type == "2T":
        return (
            boat_count
            * (boat_count - 1)
        )

    return (
        boat_count
        * (boat_count - 1)
        * (boat_count - 2)
    )


def save_market_snapshot(
    race_date,
    venue_code,
    venue_name,
    race_no,
    category,
    deadline,
    snapshot_type,
    actual_minutes,
    url,
    html,
):
    captured_at = (
        now_jst().isoformat()
    )

    with connect() as con:
        cursor = con.execute(
            """
            INSERT INTO market_snapshots (
                race_date,
                venue_code,
                venue_name,
                race_no,
                category,
                deadline,
                snapshot_type,
                fetched_at,
                minutes_to_deadline,
                pre_deadline,
                source_url,
                raw_html
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                race_date,
                venue_code,
                venue_name,
                race_no,
                category,
                deadline,
                snapshot_type,
                captured_at,
                actual_minutes,
                url,
                html,
            ),
        )

        snapshot_id = (
            cursor.lastrowid
        )

    return snapshot_id, captured_at


def save_checkpoint(
    race_id,
    race_date,
    venue_code,
    race_no,
    bet_type,
    checkpoint,
    actual_minutes,
    snapshot_id,
    captured_at,
):
    with connect() as con:
        con.execute(
            """
            INSERT OR IGNORE INTO odds_checkpoints (
                race_id,
                race_date,
                venue_code,
                race_no,
                bet_type,
                checkpoint_minutes,
                actual_minutes,
                snapshot_id,
                captured_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                race_id,
                race_date,
                venue_code,
                race_no,
                bet_type,
                checkpoint,
                actual_minutes,
                snapshot_id,
                captured_at,
            ),
        )


def capture_one(
    race_date,
    venue_code,
    venue_name,
    race_no,
    category,
    deadline,
    actual_minutes,
    checkpoint,
    bet_type,
):
    race_id = make_race_id(
        race_date,
        venue_code,
        race_no,
    )

    if checkpoint_exists(
        race_id,
        bet_type,
        checkpoint,
    ):
        return False

    if bet_type == "2T":
        endpoint = "odds2tf"
        snapshot_type = "odds2t"
        parser = map_2t

    else:
        endpoint = "odds3t"
        snapshot_type = "odds3t"
        parser = map_3t

    url = (
        f"{BASE}/{endpoint}"
        f"?hd={race_date}"
        f"&jcd={venue_code}"
        f"&rno={race_no}"
    )

    try:
        html = fetch(url)

        odds_map = parser(html)

        expected = expected_count(
            odds_map,
            bet_type,
        )

        if (
            expected is None
            or len(odds_map)
            != expected
        ):
            print(
                "LIVE_ODDS_INVALID",
                venue_name,
                f"{race_no}R",
                bet_type,
                "checkpoint=",
                checkpoint,
                "count=",
                len(odds_map),
                flush=True,
            )

            return False

        (
            snapshot_id,
            captured_at,
        ) = save_market_snapshot(
            race_date=race_date,
            venue_code=venue_code,
            venue_name=venue_name,
            race_no=race_no,
            category=category,
            deadline=deadline,
            snapshot_type=snapshot_type,
            actual_minutes=actual_minutes,
            url=url,
            html=html,
        )

        save_odds(
            snapshot_id,
            bet_type,
            odds_map,
        )

        save_checkpoint(
            race_id=race_id,
            race_date=race_date,
            venue_code=venue_code,
            race_no=race_no,
            bet_type=bet_type,
            checkpoint=checkpoint,
            actual_minutes=actual_minutes,
            snapshot_id=snapshot_id,
            captured_at=captured_at,
        )

        print(
            "LIVE_ODDS_SAVED",
            venue_name,
            f"{race_no}R",
            bet_type,
            "checkpoint=",
            checkpoint,
            "actual=",
            round(
                actual_minutes,
                2,
            ),
            "count=",
            len(odds_map),
            flush=True,
        )

        return True

    except Exception as error:
        print(
            "LIVE_ODDS_ERROR",
            venue_name,
            f"{race_no}R",
            bet_type,
            type(error).__name__,
            str(error)[:100],
            flush=True,
        )

        return False


def capture_live_odds():
    race_date, races = (
        get_today_races()
    )

    now = now_jst()

    saved = 0

    for row in races:
        deadline_dt = deadline_datetime(
            race_date,
            row["deadline"],
        )

        if deadline_dt is None:
            continue

        minutes = (
            deadline_dt - now
        ).total_seconds() / 60

        if (
            minutes <= 0
            or minutes > 6
        ):
            continue

        checkpoint = nearest_checkpoint(
            minutes
        )

        if checkpoint is None:
            continue

        for bet_type in (
            "2T",
            "3T",
        ):
            if capture_one(
                race_date=race_date,
                venue_code=row[
                    "venue_code"
                ],
                venue_name=row[
                    "venue_name"
                ],
                race_no=row[
                    "race_no"
                ],
                category=row[
                    "category"
                ],
                deadline=row[
                    "deadline"
                ],
                actual_minutes=minutes,
                checkpoint=checkpoint,
                bet_type=bet_type,
            ):
                saved += 1

    return saved


def today_schedule_exists():
    with connect() as con:
        row = con.execute(
            """
            SELECT COUNT(*)
            FROM race_pages
            WHERE race_date=?
            """,
            (
                today_string(),
            ),
        ).fetchone()

    return (
        bool(row)
        and row[0] > 0
    )


def run_script(
    filename,
):
    print(
        "LIVE_STEP_START",
        filename,
        flush=True,
    )

    result = subprocess.run(
        [
            sys.executable,
            filename,
        ],
        check=False,
    )

    print(
        "LIVE_STEP_DONE",
        filename,
        "code=",
        result.returncode,
        flush=True,
    )

    return (
        result.returncode
        == 0
    )


def main():
    init_live_db()

    print(
        "LIVE_WORKER_START",
        now_jst().isoformat(),
        flush=True,
    )

    last_schedule_attempt = 0.0
    last_result_run = 0.0
    last_backtest_run = 0.0

    while True:
        cycle_started = (
            time.monotonic()
        )

        try:
            if not today_schedule_exists():
                if (
                    cycle_started
                    - last_schedule_attempt
                    >= SCHEDULE_RETRY_SECONDS
                    or last_schedule_attempt
                    == 0.0
                ):
                    last_schedule_attempt = (
                        cycle_started
                    )

                    run_script(
                        "collector.py"
                    )

            if today_schedule_exists():
                captured = (
                    capture_live_odds()
                )

                if captured:
                    print(
                        "LIVE_CAPTURE_DONE",
                        "saved=",
                        captured,
                        flush=True,
                    )

                    run_script(
                        "shadow_recorder.py"
                    )

            if (
                cycle_started
                - last_result_run
                >= RESULT_INTERVAL_SECONDS
            ):
                last_result_run = (
                    cycle_started
                )

                run_script(
                    "result_collector.py"
                )

            if (
                cycle_started
                - last_backtest_run
                >= BACKTEST_INTERVAL_SECONDS
            ):
                last_backtest_run = (
                    cycle_started
                )

                run_script(
                    "shadow_backtest.py"
                )

        except Exception as error:
            print(
                "LIVE_WORKER_ERROR",
                type(error).__name__,
                str(error)[:160],
                flush=True,
            )

        elapsed = (
            time.monotonic()
            - cycle_started
        )

        sleep_seconds = max(
            1,
            POLL_SECONDS
            - elapsed,
        )

        time.sleep(
            sleep_seconds
        )


if __name__ == "__main__":
    main()
