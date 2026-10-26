import os
import sqlite3

from racer_data_parser import (
    RacerTableParser,
    evaluate_data_readiness,
)


DB = os.environ.get(
    "DB_PATH",
    "/data/boatrace_ev.sqlite3",
)

MAX_RACES = 12

KEYWORDS = (
    "全国勝率",
    "勝率",
    "モーター",
    "展示",
    "平均ST",
    "平均スタート",
    "進入",
    "コース",
)


def get_latest_beforeinfo():
    with sqlite3.connect(DB) as con:
        row = con.execute(
            """
            SELECT MAX(race_date)
            FROM market_snapshots
            WHERE snapshot_type='beforeinfo'
            """
        ).fetchone()

        if not row or not row[0]:
            return None, []

        race_date = row[0]

        rows = con.execute(
            """
            SELECT
                m.venue_code,
                m.venue_name,
                m.race_no,
                m.category,
                m.deadline,
                m.fetched_at,
                m.raw_html
            FROM market_snapshots AS m
            INNER JOIN (
                SELECT
                    venue_code,
                    race_no,
                    MAX(id) AS latest_id
                FROM market_snapshots
                WHERE race_date=?
                  AND snapshot_type='beforeinfo'
                  AND pre_deadline=1
                  AND category != 'female'
                GROUP BY
                    venue_code,
                    race_no
            ) AS latest
                ON m.id = latest.latest_id
            ORDER BY
                m.id DESC
            LIMIT ?
            """,
            (
                race_date,
                MAX_RACES,
            ),
        ).fetchall()

    return race_date, rows


def diagnostic_rows(html):
    parser = RacerTableParser()
    parser.feed(html)

    found = []

    for row in parser.rows:
        text = " | ".join(
            part.strip()
            for part in row
            if part.strip()
        )

        if not text:
            continue

        if any(
            keyword in text
            for keyword in KEYWORDS
        ):
            found.append(text[:300])

    return found[:8]


def main():
    print(
        "RACER_DATA_PROBE_START",
        "db=",
        DB,
        flush=True,
    )

    race_date, rows = get_latest_beforeinfo()

    if not race_date:
        print(
            "RACER_DATA_PROBE_NO_DATE",
            flush=True,
        )
        return

    print(
        "RACER_DATA_PROBE_DATE",
        race_date,
        "races=",
        len(rows),
        flush=True,
    )

    ready = 0
    skipped = 0

    for (
        venue_code,
        venue_name,
        race_no,
        category,
        deadline,
        fetched_at,
        raw_html,
    ) in rows:

        result = evaluate_data_readiness(
            raw_html
        )

        if result["status"] == "READY_FOR_VALIDATION":
            ready += 1

            print(
                "PROBE_READY",
                venue_name,
                f"{race_no}R",
                "boats=",
                len(result["boats"]),
                "category=",
                category,
                flush=True,
            )

            for boat in result["boats"]:
                print(
                    "BOAT",
                    boat.number,
                    "win=",
                    boat.racer_win_rate,
                    "motor=",
                    boat.motor_2rate,
                    "exhibition=",
                    boat.exhibition_time,
                    "st=",
                    boat.average_st,
                    "course=",
                    boat.course,
                    flush=True,
                )

        else:
            skipped += 1

            print(
                "PROBE_SKIP",
                venue_name,
                f"{race_no}R",
                result["reason"],
                "category=",
                category,
                "deadline=",
                deadline,
                flush=True,
            )

            rows_found = diagnostic_rows(
                raw_html
            )

            if not rows_found:
                print(
                    "DIAG",
                    "no matching table labels found",
                    flush=True,
                )

            for diag in rows_found:
                print(
                    "DIAG",
                    diag,
                    flush=True,
                )

    print(
        "RACER_DATA_PROBE_DONE",
        "date=",
        race_date,
        "checked=",
        len(rows),
        "ready=",
        ready,
        "skipped=",
        skipped,
        flush=True,
    )


if __name__ == "__main__":
    main()
