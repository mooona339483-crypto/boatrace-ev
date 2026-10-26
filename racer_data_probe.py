import os
import sqlite3

from combined_racer_parser import (
    evaluate_combined_readiness,
    parse_exhibition_times,
    parse_racelist,
    parse_start_courses,
)


DB = os.environ.get(
    "DB_PATH",
    "/data/boatrace_ev.sqlite3",
)

MAX_RACES = 12


def get_latest_races():
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
                m.venue_name,
                m.race_no,
                r.raw_html,
                m.raw_html
            FROM market_snapshots AS m

            INNER JOIN race_pages AS r
                ON r.race_date = m.race_date
                AND r.venue_code = m.venue_code
                AND r.race_no = m.race_no

            WHERE m.race_date = ?
              AND m.snapshot_type = 'beforeinfo'
              AND m.pre_deadline = 1
              AND m.category != 'female'

              AND m.id = (
                  SELECT MAX(m2.id)
                  FROM market_snapshots AS m2
                  WHERE m2.race_date = m.race_date
                    AND m2.venue_code = m.venue_code
                    AND m2.race_no = m.race_no
                    AND m2.snapshot_type = 'beforeinfo'
                    AND m2.pre_deadline = 1
              )

              AND r.fetched_at = (
                  SELECT MAX(r2.fetched_at)
                  FROM race_pages AS r2
                  WHERE r2.race_date = r.race_date
                    AND r2.venue_code = r.venue_code
                    AND r2.race_no = r.race_no
              )

            ORDER BY m.id DESC
            LIMIT ?
            """,
            (
                race_date,
                MAX_RACES,
            ),
        ).fetchall()

    return race_date, rows


def main():
    print(
        "NUMERIC_PROBE_START",
        "db=",
        DB,
        flush=True,
    )

    try:
        race_date, rows = get_latest_races()

    except sqlite3.Error as error:
        print(
            "NUMERIC_PROBE_DB_ERROR",
            str(error)[:200],
            flush=True,
        )
        return

    if not race_date:
        print(
            "NUMERIC_PROBE_NO_DATA",
            flush=True,
        )
        return

    ready = 0
    skipped = 0
    sample_printed = False

    for (
        venue_name,
        race_no,
        racelist_html,
        beforeinfo_html,
    ) in rows:

        racelist = parse_racelist(
            racelist_html
        )

        exhibition = parse_exhibition_times(
            beforeinfo_html
        )

        courses = parse_start_courses(
            beforeinfo_html
        )

        result = evaluate_combined_readiness(
            racelist_html,
            beforeinfo_html,
        )

        print(
            "NUMERIC_RACE",
            venue_name,
            f"{race_no}R",
            result["status"],
            "racers=",
            len(racelist),
            "exhibition=",
            len(exhibition),
            "courses=",
            len(courses),
            flush=True,
        )

        if result["status"] != "READY_FOR_MODEL":
            skipped += 1
            continue

        ready += 1

        if not sample_printed:
            print(
                "NUMERIC_SAMPLE",
                venue_name,
                f"{race_no}R",
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
                    "avgST=",
                    boat.average_st,
                    "course=",
                    boat.course,
                    flush=True,
                )

            sample_printed = True

    print(
        "NUMERIC_PROBE_DONE",
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
