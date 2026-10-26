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


def parse_racelist(html):
    rows = parse_rows(html)

    racers = {}

    for row in rows:
        cells = [
            cell.strip()
            for cell in row
        ]

        st_index = None
        average_st = None

        for index, cell in enumerate(
            cells
        ):
            value = average_st_from_cell(
                cell
            )

            if value is not None:
                st_index = index
                average_st = value
                break

        if st_index is None:
            continue

        boat_number = exact_boat_number(
            cells[:st_index]
        )

        if boat_number is None:
            continue

        groups = []

        for cell in cells[
            st_index + 1:
        ]:
            values = numeric_values(cell)

            if len(values) >= 3:
                groups.append(values)

            if len(groups) >= 4:
                break

        # 全国 / 当地 / モーター / ボート
        if len(groups) < 3:
            continue

        national = groups[0]
        local = groups[1]
        motor = groups[2]

        racer_win_rate = national[0]
        local_win_rate = local[0]
        motor_2rate = motor[1]

        if not (
            0 <= average_st <= 1
            and 0 <= racer_win_rate <= 10
            and 0 <= local_win_rate <= 10
            and 0 <= motor_2rate <= 100
        ):
            continue

        racers[boat_number] = {
            "racer_win_rate":
                racer_win_rate,
            "local_win_rate":
                local_win_rate,
            "motor_2rate":
                motor_2rate,
            "average_st":
                average_st,
        }

    return racers


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
