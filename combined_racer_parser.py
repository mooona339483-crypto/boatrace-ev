import math
import re
from html.parser import HTMLParser

from racer_data_parser import RacerData


FULLWIDTH_TABLE = str.maketrans(
    "０１２３４５６７８９．－",
    "0123456789.-",
)


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []

        elif (
            tag in ("td", "th")
            and self.row is not None
        ):
            self.cell = tag
            self.parts = []

    def handle_data(self, data):
        if self.cell is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if (
            tag in ("td", "th")
            and self.cell == tag
        ):
            value = " ".join(
                self.parts
            )

            value = " ".join(
                value.split()
            )

            value = value.translate(
                FULLWIDTH_TABLE
            )

            self.row.append(value)

            self.cell = None
            self.parts = []

        elif (
            tag == "tr"
            and self.row is not None
        ):
            if self.row:
                self.rows.append(
                    self.row
                )

            self.row = None


def parse_rows(html):
    if not isinstance(html, str):
        raise ValueError(
            "HTML must be text"
        )

    parser = TableParser()
    parser.feed(html)

    return parser.rows


def numeric_values(value):
    values = []

    for match in re.findall(
        r"-?\d+(?:\.\d+)?",
        value,
    ):
        try:
            number = float(match)
        except ValueError:
            continue

        if math.isfinite(number):
            values.append(number)

    return values


def exact_boat_number(cells):
    for cell in cells:
        value = cell.strip()

        if value in (
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
        ):
            return int(value)

    return None


def average_st_from_cell(cell):
    if (
        "F" not in cell
        and "L" not in cell
    ):
        return None

    matches = re.findall(
        r"(?<!\d)"
        r"(?:0?\.\d{1,3}|0\.\d{1,3})"
        r"(?!\d)",
        cell,
    )

    for value in reversed(matches):
        try:
            number = float(value)
        except ValueError:
            continue

        if 0 <= number <= 1:
            return number

    return None


class RacelistTableParser(TableParser):
    """Keep official cell structure alongside the unchanged text parser."""
    def __init__(self):
        super().__init__()
        self.attributes = []
        self.row_attributes = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row_attributes = []
        elif tag in ("td", "th") and self.row is not None:
            self.row_attributes.append(dict(attrs))
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "tr" and self.row:
            self.attributes.append(self.row_attributes)
        super().handle_endtag(tag)


def parse_racelist_diagnostic(html):
    """Parse the verified eight-cell prefix without shifting missing columns.

    Retain a recognized boat's partial fields for diagnostics, never invent
    absent values. Unknown row structure yields no usable statistics.
    """
    if not isinstance(html, str):
        raise ValueError("HTML must be text")
    parser = RacelistTableParser()
    parser.feed(html)
    racers = {}
    seen = set()
    for row, attrs in zip(parser.rows, parser.attributes):
        if not row or row[0].strip() not in ("1", "2", "3", "4", "5", "6"):
            continue
        # Ignore continuation/header tables, whose first cell may also be 1..6.
        if len(row) < 4 or re.match(r"F\d+\s+L\d+(?:\s|$)", row[3].strip()) is None:
            continue
        number = int(row[0].strip())
        # Only the observed official layout is supported. Never infer columns
        # from a later numeric cell when a statistics td has disappeared.
        if (len(attrs) != len(row) or len(attrs) < 8
                or f"is-boatColor{number}" not in (attrs[0].get("class") or "").split()
                or any(a.get("rowspan") != "4" or a.get("colspan", "1") != "1"
                       for a in attrs[:8])
                or any("is-lineH2" not in (a.get("class") or "").split()
                       for a in attrs[3:8])):
            continue
        if number in seen:
            racers[number] = {}
            continue
        seen.add(number)
        racers[number] = {}
        if len(row) < 8:
            continue
        # Verified layout: boat/photo/profile/ST/national/local/motor/boat.
        st = re.fullmatch(r"F\d+\s+L\d+\s+(-|0?\.\d{1,3})", row[3].strip())
        if st is None:
            continue
        groups = []
        for cell in row[4:8]:
            tokens = cell.split()
            if len(tokens) != 3 or any(
                re.fullmatch(r"(?:\d+(?:\.\d+)?|-)", token) is None
                for token in tokens
            ):
                break
            groups.append([None if token == "-" else float(token) for token in tokens])
        if len(groups) != 4:
            continue
        national, local, motor, boat = groups
        def bounded(value, maximum):
            return value is None or (math.isfinite(value) and 0 <= value <= maximum)
        if any(not bounded(g[0], 10) or any(not bounded(v, 100) for v in g[1:])
               for g in (national, local)):
            continue
        if any(g[0] is None or not math.isfinite(g[0]) or not g[0].is_integer()
               or not 1 <= g[0] <= 999 or any(not bounded(v, 100) for v in g[1:])
               for g in (motor, boat)):
            continue
        # Local figures were required by the old parser; do not relax that gate.
        if any(v is None for v in local + national[1:] + motor[2:]):
            continue
        average_st = None if st.group(1) == "-" else float(st.group(1))
        if average_st is not None and not 0 <= average_st <= 1:
            continue
        racers[number] = {
            "racer_win_rate": national[0],
            "local_win_rate": local[0],
            "motor_2rate": motor[1],
            "average_st": average_st,
        }
    return racers


def parse_racelist(html):
    """Keep the complete-input interface for existing model callers."""
    return {
        number: data for number, data in parse_racelist_diagnostic(html).items()
        if data and all(data.get(field) is not None for field in (
            "racer_win_rate", "local_win_rate", "motor_2rate", "average_st"
        ))
    }


def parse_exhibition_times(html):
    rows = parse_rows(html)

    exhibition = {}

    for row in rows:
        cells = [
            cell.strip()
            for cell in row
        ]

        boat_number = (
            exact_boat_number(
                cells[:3]
            )
        )

        if boat_number is None:
            continue

        candidates = []

        for cell in cells:
            for value in numeric_values(
                cell
            ):
                if 5.0 <= value <= 10.0:
                    candidates.append(
                        value
                    )

        if not candidates:
            continue

        exhibition[
            boat_number
        ] = candidates[0]

    return exhibition


def parse_start_courses(html):
    rows = parse_rows(html)

    header_index = None

    for index, row in enumerate(rows):
        text = " ".join(row)

        if (
            "コース" in text
            and "並び" in text
            and "ST" in text
        ):
            header_index = index
            break

    if header_index is None:
        return {}

    course_map = {}

    course = 1

    for row in rows[
        header_index + 1:
    ]:
        if course > 6:
            break

        cells = [
            cell.strip()
            for cell in row
        ]

        boat_number = (
            exact_boat_number(cells)
        )

        if boat_number is None:
            if course_map:
                break

            continue

        if boat_number in course_map:
            break

        course_map[
            boat_number
        ] = course

        course += 1

    return course_map


def parse_combined_racer_data(
    racelist_html,
    beforeinfo_html,
):
    racelist = parse_racelist(
        racelist_html
    )

    exhibition = (
        parse_exhibition_times(
            beforeinfo_html
        )
    )

    courses = parse_start_courses(
        beforeinfo_html
    )

    active_boats = sorted(
        set(racelist)
        & set(exhibition)
        & set(courses)
    )

    if len(active_boats) not in (
        5,
        6,
    ):
        return []

    course_values = [
        courses[number]
        for number in active_boats
    ]

    if len(
        set(course_values)
    ) != len(course_values):
        return []

    result = []

    for number in active_boats:
        data = racelist[number]

        result.append(
            RacerData(
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

    return result


def evaluate_combined_readiness(
    racelist_html,
    beforeinfo_html,
):
    try:
        racers = (
            parse_combined_racer_data(
                racelist_html,
                beforeinfo_html,
            )
        )

    except (
        ValueError,
        TypeError,
    ):
        return {
            "status": "SKIP",
            "reason":
                "INVALID_COMBINED_DATA",
            "boats": [],
        }

    if not racers:
        return {
            "status": "SKIP",
            "reason":
                "MISSING_COMBINED_DATA",
            "boats": [],
        }

    return {
        "status":
            "READY_FOR_MODEL",
        "reason":
            "COMBINED_DATA_EXTRACTED",
        "boats":
            racers,
    }


if __name__ == "__main__":
    print(
        "COMBINED_RACER_PARSER_READY"
    )
