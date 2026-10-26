import os
import sqlite3

from boatcast_preview import fetch_preview
from combined_racer_parser import parse_racelist
from probability_model import (
    Boat,
    predict_probabilities,
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
                m.venue_code,
                m.venue_name,
                m.race_no,
                r.raw_html
            FROM market_snapshots AS m

            INNER JOIN race_pages AS r
                ON r.race_date = m.race_date
                AND r.venue_code = m.venue_code
                AND r.race_no = m.race_no

            WHERE m.race_date=?
              AND m.snapshot_type='beforeinfo'
              AND m.pre_deadline=1
              AND m.category != 'female'

              AND m.id = (
                  SELECT MAX(m2.id)
                  FROM market_snapshots AS m2
                  WHERE m2.race_date=m.race_date
                    AND m2.venue_code=m.venue_code
                    AND m2.race_no=m.race_no
                    AND m2.snapshot_type='beforeinfo'
                    AND m2.pre_deadline=1
              )

              AND r.fetched_at = (
                  SELECT MAX(r2.fetched_at)
                  FROM race_pages AS r2
                  WHERE r2.race_date=r.race_date
                    AND r2.venue_code=r.venue_code
                    AND r2.race_no=r.race_no
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


def build_model_boats(
    racelist,
    preview,
):
    exhibition = preview["exhibition"]
    courses = preview["courses"]

    active = sorted(
        set(racelist)
        & set(exhibition)
        & set(courses)
    )

    if len(active) not in (5, 6):
        return []

    course_values = [
        courses[number]
        for number in active
    ]

    if len(set(course_values)) != len(course_values):
        return []

    boats = []

    for number in active:
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
                course=courses[number],
            )
        )

    return boats


def top_items(
    probabilities,
    count=5,
):
    return sorted(
        probabilities.items(),
        key=lambda item: (
            -item[1],
            item[0],
        ),
    )[:count]


def main():
    print(
        "MODEL_PROBE_START",
        "UNVERIFIED_MODEL",
        flush=True,
    )

    race_date, rows = get_latest_races()

    if not race_date:
        print(
            "MODEL_PROBE_NO_DATA",
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

        try:
            racelist = parse_racelist(
                racelist_html
            )

            preview = fetch_preview(
                race_date,
                venue_code,
                race_no,
            )

            if preview["status"] != "READY":
                skipped += 1

                print(
                    "MODEL_RACE",
                    venue_name,
                    f"{race_no}R",
                    "SKIP",
                    preview["reason"],
                    flush=True,
                )
                continue

            boats = build_model_boats(
                racelist,
                preview,
            )

            if len(boats) not in (5, 6):
                skipped += 1

                print(
                    "MODEL_RACE",
                    venue_name,
                    f"{race_no}R",
                    "SKIP",
                    "INCOMPLETE_BOATS",
                    flush=True,
                )
                continue

            prob_2t = predict_probabilities(
                boats,
                "2T",
            )

            prob_3t = predict_probabilities(
                boats,
                "3T",
            )

            ready += 1

            best_2t = top_items(
                prob_2t,
                1,
            )[0]

            best_3t = top_items(
                prob_3t,
                1,
            )[0]

            print(
                "MODEL_RACE",
                venue_name,
                f"{race_no}R",
                "READY",
                "boats=",
                len(boats),
                "2T=",
                len(prob_2t),
                "3T=",
                len(prob_3t),
                "top2T=",
                best_2t[0],
                round(best_2t[1], 4),
                "top3T=",
                best_3t[0],
                round(best_3t[1], 4),
                flush=True,
            )

            if not sample_printed:
                print(
                    "MODEL_SAMPLE",
                    venue_name,
                    f"{race_no}R",
                    "UNVERIFIED",
                    flush=True,
                )

                for selection, probability in top_items(
                    prob_2t,
                    5,
                ):
                    print(
                        "TOP_2T",
                        selection,
                        round(probability, 6),
                        flush=True,
                    )

                for selection, probability in top_items(
                    prob_3t,
                    5,
                ):
                    print(
                        "TOP_3T",
                        selection,
                        round(probability, 6),
                        flush=True,
                    )

                sample_printed = True

        except Exception as error:
            skipped += 1

            print(
                "MODEL_RACE",
                venue_name,
                f"{race_no}R",
                "ERROR",
                type(error).__name__,
                str(error)[:120],
                flush=True,
            )

    print(
        "MODEL_PROBE_DONE",
        "date=",
        race_date,
        "checked=",
        len(rows),
        "ready=",
        ready,
        "skipped=",
        skipped,
        "verified=",
        False,
        flush=True,
    )


if __name__ == "__main__":
    main()
