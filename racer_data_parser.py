import os
import sqlite3

from boatcast_preview import fetch_preview
from combined_racer_parser import parse_racelist
from racer_data_parser import RacerData


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
                m.venue_code,
                m.venue_name,
                m.race_no,
                r.raw_html
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


def build_boats(
    racelist,
    preview,
):
    exhibition = preview[
        "exhibition"
    ]

    courses = preview[
        "courses"
    ]

    active = sorted(
        set(racelist)
        & set(exhibition)
        & set(courses)
    )

    if len(active) not in (
        5,
        6,
    ):
        return []

    boats = []

    for number in active:
        base = racelist[number]

        boats.append(
            RacerData(
                number=number,
                racer_win_rate=base[
                    "racer_win_rate"
                ],
                motor_2rate=base[
                    "motor_2rate"
                ],
                exhibition_time=(
                    exhibition[number]
                ),
                average_st=base[
                    "average_st"
                ],
                course=courses[number],
            )
        )

    return boats


def main():
    print(
        "BOATCAST_PROBE_START",
        "db=",
        DB,
        flush=True,
    )

    try:
        race_date, rows = get_latest_races()

    except sqlite3.Error as error:
        print(
            "BOATCAST_PROBE_DB_ERROR",
            str(error)[:200],
            flush=True,
        )
        return

    if not race_date:
        print(
            "BOATCAST_PROBE_NO_DATA",
            flush=True,
        )
        return

    ready = 0
    skipped = 0
    sample_printed = False

    for (
        venue_code,
        venue_name,
        race_no,
        racelist_html,
    ) in rows:

        racelist = parse_racelist(
            racelist_html
        )

        preview = fetch_preview(
            race_date,
            venue_code,
            race_no,
        )

        boats = []

        if preview["status"] == "READY":
            boats = build_boats(
                racelist,
                preview,
            )

        if len(boats) in (
            5,
            6,
        ):
            ready += 1
            status = "READY_FOR_MODEL"

        else:
            skipped += 1
            status = "SKIP"

        print(
            "BOATCAST_RACE",
            venue_name,
            f"{race_no}R",
            status,
            "racers=",
            len(racelist),
            "exhibition=",
            len(
                preview["exhibition"]
            ),
            "courses=",
            len(
                preview["courses"]
            ),
            "reason=",
            preview["reason"],
            flush=True,
        )

        if (
            status == "READY_FOR_MODEL"
            and not sample_printed
        ):
            print(
                "BOATCAST_SAMPLE",
                venue_name,
                f"{race_no}R",
                flush=True,
            )

            for boat in boats:
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
        "BOATCAST_PROBE_DONE",
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
