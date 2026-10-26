import os
import sqlite3
from collections import Counter
from html.parser import HTMLParser

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
    "枠",
    "ボートレーサー",
    "勝率",
    "全国",
    "当地",
    "モーター",
    "2連",
    "展示",
    "平均ST",
    "平均スタート",
    "進入",
    "コース",
    "欠場",
)

class PageInspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.titles = []
        self.text = []
        self.capture_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.capture_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.capture_title = False

    def handle_data(self, data):
        value = " ".join(data.split())
        if not value:
            return

        if self.capture_title:
            self.titles.append(value)

        self.text.append(value)


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
                GROUP BY venue_code, race_no
            ) AS latest
                ON m.id = latest.latest_id
            ORDER BY m.id DESC
            LIMIT ?
            """,
            (race_date, MAX_RACES),
        ).fetchall()

    return race_date, rows


def inspect_html(html):
    if not isinstance(html, str):
        print(
            "DIAG_HTML_INVALID",
            type(html).__name__,
            flush=True,
        )
        return

    print(
        "DIAG_HTML_LENGTH",
        len(html),
        flush=True,
    )

    page = PageInspector()
    page.feed(html)

    print(
        "DIAG_TITLE",
        " ".join(page.titles)[:160],
        flush=True,
    )

    parser = RacerTableParser()
    parser.feed(html)

    print(
        "DIAG_ROW_COUNT",
        len(parser.rows),
        flush=True,
    )

    matched = []

    for index, row in enumerate(parser.rows):
        line = " | ".join(
            " ".join(str(cell).split())
            for cell in row
        )

        if any(word in line for word in KEYWORDS):
            matched.append((index, line))

    print(
        "DIAG_MATCHED_ROWS",
        len(matched),
        flush=True,
    )

    for index, line in matched[:12]:
        print(
            "DIAG_ROW",
            index,
            line[:350],
            flush=True,
        )

        for offset in (1, 2):
            next_index = index + offset

            if next_index < len(parser.rows):
                next_row = parser.rows[next_index]

                print(
                    "DIAG_NEXT",
                    next_index,
                    " | ".join(
                        str(x) for x in next_row
                    )[:350],
                    flush=True,
                )

    text = " ".join(page.text)

    for word in KEYWORDS:
        print(
            "DIAG_FIELD",
            word,
            "present=",
            word in text,
            flush=True,
        )


def main():
    print(
        "RACER_DATA_PROBE_START",
        "db=",
        DB,
        flush=True,
    )

    try:
        race_date, rows = get_latest_beforeinfo()
    except sqlite3.Error as error:
        print(
            "PROBE_DB_ERROR",
            type(error).__name__,
            str(error)[:200],
            flush=True,
        )
        return

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

    counts = Counter()

    for row in rows:
        (
            venue_code,
            venue_name,
            race_no,
            category,
            deadline,
            fetched_at,
            raw_html,
        ) = row

        print(
            "PROBE_RACE",
            venue_name,
            f"{race_no}R",
            "category=",
            category,
            "deadline=",
            deadline,
            flush=True,
        )

        result = evaluate_data_readiness(raw_html)

        status = result["status"]
        counts[status] += 1

        print(
            "PROBE_RESULT",
            status,
            result["reason"],
            "boats=",
            len(result["boats"]),
            flush=True,
        )

        if status == "READY_FOR_VALIDATION":
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
            inspect_html(raw_html)

    ready = counts["READY_FOR_VALIDATION"]
    skipped = len(rows) - ready

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
