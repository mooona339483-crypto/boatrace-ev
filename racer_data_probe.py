import os
import sqlite3
from html.parser import HTMLParser


DB = os.environ.get(
    "DB_PATH",
    "/data/boatrace_ev.sqlite3",
)

MAX_RACES = 12


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = " ".join(data.split())

        if text:
            self.parts.append(text)

    def get_text(self):
        return " ".join(self.parts)


def html_text(html):
    parser = TextParser()
    parser.feed(html)

    return parser.get_text()


def get_latest_combined_races():
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
                r.raw_html AS racelist_html,
                m.raw_html AS beforeinfo_html
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


def has_any(text, words):
    return any(
        word in text
        for word in words
    )


def main():
    print(
        "COMBINED_PROBE_START",
        "db=",
        DB,
        flush=True,
    )

    try:
        race_date, rows = (
            get_latest_combined_races()
        )

    except sqlite3.Error as error:
        print(
            "COMBINED_PROBE_DB_ERROR",
            type(error).__name__,
            str(error)[:200],
            flush=True,
        )
        return

    if not race_date:
        print(
            "COMBINED_PROBE_NO_DATE",
            flush=True,
        )
        return

    print(
        "COMBINED_PROBE_DATE",
        race_date,
        "races=",
        len(rows),
        flush=True,
    )

    complete = 0
    incomplete = 0

    for (
        venue_code,
        venue_name,
        race_no,
        category,
        deadline,
        racelist_html,
        beforeinfo_html,
    ) in rows:

        racelist_text = html_text(
            racelist_html
        )

        beforeinfo_text = html_text(
            beforeinfo_html
        )

        average_st = has_any(
            racelist_text,
            (
                "平均ST",
                "平均スタート",
            ),
        )

        national = (
            "全国" in racelist_text
        )

        local = (
            "当地" in racelist_text
        )

        motor = (
            "モーター" in racelist_text
            and has_any(
                racelist_text,
                (
                    "2連率",
                    "2連",
                ),
            )
        )

        exhibition = has_any(
            beforeinfo_text,
            (
                "展示タイム",
                "展示",
            ),
        )

        course = has_any(
            beforeinfo_text,
            (
                "進入",
                "コース",
            ),
        )

        ok = all(
            (
                average_st,
                national,
                local,
                motor,
                exhibition,
                course,
            )
        )

        if ok:
            complete += 1
            status = "COMPLETE"

        else:
            incomplete += 1
            status = "INCOMPLETE"

        print(
            "COMBINED_RACE",
            venue_name,
            f"{race_no}R",
            status,
            "avgST=",
            int(average_st),
            "national=",
            int(national),
            "local=",
            int(local),
            "motor=",
            int(motor),
            "exhibition=",
            int(exhibition),
            "course=",
            int(course),
            flush=True,
        )

    print(
        "COMBINED_PROBE_DONE",
        "date=",
        race_date,
        "checked=",
        len(rows),
        "complete=",
        complete,
        "incomplete=",
        incomplete,
        flush=True,
    )


if __name__ == "__main__":
    main()
