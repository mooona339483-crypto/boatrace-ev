import os
import re
import sqlite3
from html.parser import HTMLParser

DB = os.environ.get(
    "DB_PATH",
    "/data/boatrace_ev.sqlite3"
)


class OddsTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row = None
        self.current_cell = None
        self.current_rowspan = 1
        self.current_colspan = 1

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "tr":
            self.current_row = []

        elif tag in ("td", "th"):
            self.current_cell = []
            self.current_rowspan = int(
                attrs.get("rowspan", "1")
            )
            self.current_colspan = int(
                attrs.get("colspan", "1")
            )

    def handle_data(self, data):
        if self.current_cell is not None:
            text = data.strip()

            if text:
                self.current_cell.append(text)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            if (
                self.current_row is not None
                and self.current_cell is not None
            ):
                text = " ".join(
                    self.current_cell
                ).strip()

                self.current_row.append(
                    {
                        "text": text,
                        "rowspan": self.current_rowspan,
                        "colspan": self.current_colspan,
                    }
                )

            self.current_cell = None

        elif tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)

            self.current_row = None


def extract_table_after(html, marker):
    pos = html.find(marker)

    if pos < 0:
        return None

    part = html[pos:]

    m = re.search(
        r"<table\b[^>]*>.*?</table>",
        part,
        flags=re.I | re.S,
    )

    if not m:
        return None

    return m.group(0)


def expand_grid(rows):
    grid = []
    pending = {}

    for row_index, row in enumerate(rows):
        out = []
        col = 0

        while col in pending:
            value, remaining = pending[col]
            out.append(value)

            if remaining <= 1:
                del pending[col]
            else:
                pending[col] = (
                    value,
                    remaining - 1,
                )

            col += 1

        for cell in row:
            while col in pending:
                value, remaining = pending[col]
                out.append(value)

                if remaining <= 1:
                    del pending[col]
                else:
                    pending[col] = (
                        value,
                        remaining - 1,
                    )

                col += 1

            text = cell["text"]
            rowspan = cell["rowspan"]
            colspan = cell["colspan"]

            for _ in range(colspan):
                out.append(text)

                if rowspan > 1:
                    pending[col] = (
                        text,
                        rowspan - 1,
                    )

                col += 1

        while col in pending:
            value, remaining = pending[col]
            out.append(value)

            if remaining <= 1:
                del pending[col]
            else:
                pending[col] = (
                    value,
                    remaining - 1,
                )

            col += 1

        grid.append(out)

    return grid


def parse_table(html, marker):
    table_html = extract_table_after(
        html,
        marker,
    )

    if not table_html:
        return []

    parser = OddsTableParser()
    parser.feed(table_html)

    return expand_grid(parser.rows)


def to_int(value):
    value = value.strip()

    if re.fullmatch(r"[1-6]", value):
        return int(value)

    return None


def to_float(value):
    value = value.strip()

    if not re.fullmatch(
        r"\d+(?:\.\d+)?",
        value,
    ):
        return None

    try:
        return float(value)
    except ValueError:
        return None


def map_2t(html):
    grid = parse_table(
        html,
        "2連単オッズ",
    )

    found = {}

    for row in grid:
        if len(row) < 12:
            continue

        for first_index in range(6):
            base = first_index * 2

            if base + 1 >= len(row):
                continue

            second = to_int(row[base])
            odds = to_float(row[base + 1])

            first = first_index + 1

            if (
                second is None
                or odds is None
                or first == second
            ):
                continue

            key = f"{first}-{second}"
            found[key] = odds

    return found


def map_3t(html):
    grid = parse_table(
        html,
        "3連単オッズ",
    )

    found = {}

    for row in grid:
        if len(row) < 18:
            continue

        for first_index in range(6):
            base = first_index * 3

            if base + 2 >= len(row):
                continue

            second = to_int(row[base])
            third = to_int(row[base + 1])
            odds = to_float(row[base + 2])

            first = first_index + 1

            if (
                second is None
                or third is None
                or odds is None
            ):
                continue

            if len({
                first,
                second,
                third,
            }) != 3:
                continue

            key = (
                f"{first}-{second}-{third}"
            )

            found[key] = odds

    return found


def init_db():
    with sqlite3.connect(DB) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS mapped_odds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                bet_type TEXT NOT NULL,
                selection TEXT NOT NULL,
                odds REAL NOT NULL,
                UNIQUE(
                    snapshot_id,
                    bet_type,
                    selection
                )
            )
            """
        )

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mapped_odds
            ON mapped_odds (
                snapshot_id,
                bet_type,
                selection
            )
            """
        )


def save_odds(
    snapshot_id,
    bet_type,
    odds_map,
):
    with sqlite3.connect(DB) as con:
        con.execute(
            """
            DELETE FROM mapped_odds
            WHERE snapshot_id=?
              AND bet_type=?
            """,
            (
                snapshot_id,
                bet_type,
            ),
        )

        for selection, odds in odds_map.items():
            con.execute(
                """
                INSERT INTO mapped_odds (
                    snapshot_id,
                    bet_type,
                    selection,
                    odds
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    bet_type,
                    selection,
                    odds,
                ),
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
              AND snapshot_type
                  IN ('odds2t', 'odds3t')
            ORDER BY id
            """
        ).fetchall()

    processed = 0
    valid = 0
    errors = 0

    for (
        snapshot_id,
        snapshot_type,
        raw_html,
    ) in rows:

        try:
            if snapshot_type == "odds2t":
                odds_map = map_2t(
                    raw_html
                )

                expected = 30
                bet_type = "2T"

            else:
                odds_map = map_3t(
                    raw_html
                )

                expected = 120
                bet_type = "3T"

            processed += 1

            if len(odds_map) != expected:
                print(
                    "ODDS_MAP_INVALID",
                    snapshot_id,
                    bet_type,
                    "count=",
                    len(odds_map),
                    "expected=",
                    expected,
                )

                errors += 1
                continue

            save_odds(
                snapshot_id,
                bet_type,
                odds_map,
            )

            valid += 1

            print(
                "ODDS_MAPPED",
                snapshot_id,
                bet_type,
                "count=",
                len(odds_map),
            )

        except Exception as e:
            errors += 1

            print(
                "ODDS_MAP_ERROR",
                snapshot_id,
                snapshot_type,
                repr(e),
            )

    print(
        "ODDS_MAPPER_DONE",
        "processed=",
        processed,
        "valid=",
        valid,
        "errors=",
        errors,
    )


if __name__ == "__main__":
    run()
