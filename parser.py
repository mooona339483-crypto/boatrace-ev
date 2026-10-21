import os
import re
import sqlite3
from html.parser import HTMLParser

DB = os.environ.get(
    "DB_PATH",
    "/data/boatrace_ev.sqlite3"
)


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row = None
        self.current_cell = None
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.current_row = []

        elif tag in ("td", "th"):
            self.current_cell = []

    def handle_data(self, data):
        text = data.strip()

        if text:
            self.text_parts.append(text)

            if self.current_cell is not None:
                self.current_cell.append(text)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            if (
                self.current_row is not None
                and self.current_cell is not None
            ):
                value = " ".join(
                    self.current_cell
                ).strip()

                self.current_row.append(value)

            self.current_cell = None

        elif tag == "tr":
            if self.current_row:
                self.rows.append(
                    self.current_row
                )

            self.current_row = None

    def page_text(self):
        return " ".join(self.text_parts)


def parse_html(html):
    parser = TableParser()
    parser.feed(html)

    return parser.page_text(), parser.rows


def init_db():
    with sqlite3.connect(DB) as con:

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS parsed_market (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                snapshot_type TEXT NOT NULL,
                odds_update_time TEXT,
                is_final_odds INTEGER NOT NULL DEFAULT 0,
                numeric_count INTEGER NOT NULL DEFAULT 0,
                parsed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(snapshot_id)
            )
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS parsed_numeric_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                seq INTEGER NOT NULL,
                value REAL NOT NULL,
                UNIQUE(snapshot_id, seq)
            )
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS parsed_beforeinfo (
                snapshot_id INTEGER PRIMARY KEY,
                page_text TEXT NOT NULL
            )
            """
        )


def extract_update_time(text):
    m = re.search(
        r"オッズ更新時間\s*(\d{1,2}:\d{2})",
        text
    )

    if m:
        return m.group(1)

    return None


def is_final_odds(text):
    return 1 if "締切時オッズ" in text else 0


def extract_numeric_values(rows):
    values = []

    for row in rows:
        for cell in row:
            cell = cell.strip()

            if re.fullmatch(
                r"\d+(?:\.\d+)?",
                cell
            ):
                try:
                    value = float(cell)
                except ValueError:
                    continue

                values.append(value)

    return values


def save_parsed_market(
    snapshot_id,
    snapshot_type,
    update_time,
    final_odds,
    numeric_values,
):
    with sqlite3.connect(DB) as con:

        con.execute(
            """
            INSERT OR REPLACE INTO parsed_market (
                snapshot_id,
                snapshot_type,
                odds_update_time,
                is_final_odds,
                numeric_count
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                snapshot_type,
                update_time,
                final_odds,
                len(numeric_values),
            ),
        )

        con.execute(
            """
            DELETE FROM parsed_numeric_values
            WHERE snapshot_id=?
            """,
            (snapshot_id,),
        )

        for seq, value in enumerate(
            numeric_values,
            start=1,
        ):
            con.execute(
                """
                INSERT INTO parsed_numeric_values (
                    snapshot_id,
                    seq,
                    value
                )
                VALUES (?, ?, ?)
                """,
                (
                    snapshot_id,
                    seq,
                    value,
                ),
            )


def parse_snapshot(row):
    (
        snapshot_id,
        snapshot_type,
        raw_html,
    ) = row

    text, rows = parse_html(raw_html)

    if snapshot_type == "beforeinfo":

        with sqlite3.connect(DB) as con:
            con.execute(
                """
                INSERT OR REPLACE INTO parsed_beforeinfo (
                    snapshot_id,
                    page_text
                )
                VALUES (?, ?)
                """,
                (
                    snapshot_id,
                    text,
                ),
            )

        print(
            "PARSED_BEFOREINFO",
            snapshot_id,
        )

        return

    update_time = extract_update_time(text)

    final_odds = is_final_odds(text)

    numeric_values = extract_numeric_values(rows)

    save_parsed_market(
        snapshot_id=snapshot_id,
        snapshot_type=snapshot_type,
        update_time=update_time,
        final_odds=final_odds,
        numeric_values=numeric_values,
    )

    print(
        "PARSED_ODDS",
        snapshot_id,
        snapshot_type,
        "update=",
        update_time,
        "final=",
        final_odds,
        "values=",
        len(numeric_values),
    )


def run():
    init_db()

    with sqlite3.connect(DB) as con:

        rows = con.execute(
            """
            SELECT
                id,
                snapshot_type,
                raw_html
            FROM market_snapshots
            WHERE pre_deadline=1
            ORDER BY id
            """
        ).fetchall()

    parsed = 0
    errors = 0

    for row in rows:
        try:
            parse_snapshot(row)
            parsed += 1

        except Exception as e:
            errors += 1

            print(
                "PARSE_ERROR",
                row[0],
                repr(e),
            )

    print(
        "PARSER_DONE",
        "parsed=",
        parsed,
        "errors=",
        errors,
    )


if __name__ == "__main__":
    run()こ
