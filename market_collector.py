つimport os
import sqlite3
import urllib.request
import datetime
import time
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
DB = os.environ.get("DB_PATH", "/data/boatrace_ev.sqlite3")

BASE = "https://www.boatrace.jp/owpc/pc/race"

PAGE_TYPES = {
    "beforeinfo": "beforeinfo",
    "odds2t": "odds2tf",
    "odds3t": "odds3t",
}


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 boatrace-ev-research/1.0",
            "Accept-Language": "ja-JP,ja;q=0.9",
        },
    )

    with urllib.request.urlopen(req, timeout=20) as res:
        charset = res.headers.get_content_charset() or "utf-8"
        return res.read().decode(charset, errors="replace")


def init_db():
    with sqlite3.connect(DB) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_date TEXT NOT NULL,
                venue_code TEXT NOT NULL,
                venue_name TEXT NOT NULL,
                race_no INTEGER NOT NULL,
                category TEXT NOT NULL,
                deadline TEXT,
                snapshot_type TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                minutes_to_deadline REAL,
                pre_deadline INTEGER NOT NULL,
                source_url TEXT NOT NULL,
                raw_html TEXT NOT NULL
            )
            """
        )

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_market_race
            ON market_snapshots (
                race_date,
                venue_code,
                race_no,
                snapshot_type,
                fetched_at
            )
            """
        )


def get_today_races():
    with sqlite3.connect(DB) as con:
        row = con.execute(
            """
            SELECT MAX(race_date)
            FROM race_pages
            """
        ).fetchone()

        if not row or not row[0]:
            return None, []

        race_date = row[0]

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
            GROUP BY
                venue_code,
                venue_name,
                race_no,
                category,
                deadline
            ORDER BY venue_code, race_no
            """,
            (race_date,),
        ).fetchall()

    return race_date, rows


def deadline_datetime(race_date, deadline):
    if not deadline:
        return None

    d = datetime.datetime.strptime(
        race_date + deadline,
        "%Y%m%d%H:%M",
    )

    return d.replace(tzinfo=JST)


def save_snapshot(
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
    raw_html,
):
    with sqlite3.connect(DB) as con:
        con.execute(
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
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
                raw_html,
            ),
        )


def collect_market(window_minutes=45):
    init_db()

    race_date, races = get_today_races()
    now = datetime.datetime.now(JST)

    saved = 0
    skipped = 0
    errors = 0

    for (
        venue_code,
        venue_name,
        race_no,
        category,
        deadline,
    ) in races:

        deadline_dt = deadline_datetime(
            race_date,
            deadline,
        )

        if deadline_dt is None:
            skipped += 1
            continue

        minutes_to_deadline = (
            deadline_dt - now
        ).total_seconds() / 60

        # 締切済みは対象外
        if minutes_to_deadline <= 0:
            skipped += 1
            continue

        # 45分より先のレースも対象外
        if minutes_to_deadline > window_minutes:
            skipped += 1
            continue

        print(
            "TARGET",
            venue_name,
            f"{race_no}R",
            deadline,
            f"{minutes_to_deadline:.1f}min",
            category,
        )

        for snapshot_type, endpoint in PAGE_TYPES.items():

            url = (
                f"{BASE}/{endpoint}"
                f"?hd={race_date}"
                f"&jcd={venue_code}"
                f"&rno={race_no}"
            )

            try:
                html = fetch(url)

                fetched_at = datetime.datetime.now(
                    JST
                ).isoformat()

                current_minutes = (
                    deadline_dt
                    - datetime.datetime.now(JST)
                ).total_seconds() / 60

                pre_deadline = (
                    1 if current_minutes > 0 else 0
                )

                save_snapshot(
                    race_date=race_date,
                    venue_code=venue_code,
                    venue_name=venue_name,
                    race_no=race_no,
                    category=category,
                    deadline=deadline,
                    snapshot_type=snapshot_type,
                    fetched_at=fetched_at,
                    minutes_to_deadline=current_minutes,
                    pre_deadline=pre_deadline,
                    source_url=url,
                    raw_html=html,
                )

                saved += 1

                print(
                    "MARKET_SAVED",
                    venue_name,
                    f"{race_no}R",
                    snapshot_type,
                    f"{current_minutes:.1f}min",
                )

                time.sleep(0.5)

            except Exception as e:
                errors += 1

                print(
                    "MARKET_ERROR",
                    venue_name,
                    f"{race_no}R",
                    snapshot_type,
                    repr(e),
                )

        time.sleep(0.5)

    print(
        "MARKET_DONE",
        "date=", race_date,
        "saved=", saved,
        "skipped=", skipped,
        "errors=", errors,
    )


if __name__ == "__main__":
    collect_market()
