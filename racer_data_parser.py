
import math
import re
from dataclasses import dataclass
from html.parser import HTMLParser


REQUIRED_FIELDS = (
    "racer_win_rate",
    "motor_2rate",
    "exhibition_time",
    "average_st",
)


@dataclass(frozen=True)
class RacerData:
    number: int
    racer_win_rate: float
    motor_2rate: float
    exhibition_time: float
    average_st: float
    course: int


class RacerTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = tag
            self.parts = []

    def handle_data(self, data):
        if self.cell is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell == tag:
            self.row.append(" ".join(self.parts).strip())
            self.cell = None
            self.parts = []

        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None


def to_number(value):
    if not isinstance(value, str):
        return None

    cleaned = value.strip().replace("%", "")

    if cleaned in ("", "-", "--", "欠場"):
        return None

    try:
        number = float(cleaned)
    except ValueError:
        return None

    return number if math.isfinite(number) else None


def normalize_header(value):
    return re.sub(r"\s+", "", value)


HEADER_ALIASES = {
    "艇番": "number",
    "枠番": "number",
    "全国勝率": "racer_win_rate",
    "勝率": "racer_win_rate",
    "モーター2連対率": "motor_2rate",
    "モーター2連率": "motor_2rate",
    "展示タイム": "exhibition_time",
    "展示": "exhibition_time",
    "平均ST": "average_st",
    "平均スタート": "average_st",
    "進入コース": "course",
    "コース": "course",
}


def parse_racer_data(html):
    if not isinstance(html, str):
        raise ValueError("HTML must be text")

    parser = RacerTableParser()
    parser.feed(html)

    required = {"number", *REQUIRED_FIELDS}
    candidates = []

    for index, row in enumerate(parser.rows):
        headers = [
            HEADER_ALIASES.get(normalize_header(cell))
            for cell in row
        ]

        mapping = {
            name: position
            for position, name in enumerate(headers)
            if name is not None
        }

        if not required.issubset(mapping):
            continue

        boats = []
        seen = set()

        for data_row in parser.rows[index + 1:]:
            if len(data_row) != len(row):
                break

            number_value = to_number(
                data_row[mapping["number"]]
            )

            if (
                number_value is None
                or not number_value.is_integer()
                or not 1 <= number_value <= 6
            ):
                break

            number = int(number_value)

            if number in seen:
                raise ValueError("Duplicate boat number")

            seen.add(number)
            values = {}

            for field in REQUIRED_FIELDS:
                value = to_number(
                    data_row[mapping[field]]
                )
                if value is None:
                    return []
                values[field] = value

            course = number
            if "course" in mapping:
                course_value = to_number(
                    data_row[mapping["course"]]
                )

                if (
                    course_value is None
                    or not course_value.is_integer()
                    or not 1 <= course_value <= 6
                ):
                    return []

                course = int(course_value)

            if not (
                0 <= values["racer_win_rate"] <= 10
                and 0 <= values["motor_2rate"] <= 100
                and 5 <= values["exhibition_time"] <= 10
                and 0 <= values["average_st"] <= 1
            ):
                return []

            boats.append(
                RacerData(
                    number=number,
                    racer_win_rate=values["racer_win_rate"],
                    motor_2rate=values["motor_2rate"],
                    exhibition_time=values["exhibition_time"],
                    average_st=values["average_st"],
                    course=course,
                )
            )

        if boats:
            candidates.append(boats)

    if len(candidates) != 1:
        return []

    boats = candidates[0]

    if len(boats) not in (5, 6):
        return []

    if len({boat.course for boat in boats}) != len(boats):
        return []

    return sorted(boats, key=lambda boat: boat.number)


def evaluate_data_readiness(html):
    try:
        boats = parse_racer_data(html)
    except (ValueError, TypeError):
        return {
            "status": "SKIP",
            "reason": "INVALID_RACER_DATA",
            "boats": [],
        }

    if not boats:
        return {
            "status": "SKIP",
            "reason": "MISSING_OR_INCOMPLETE_DATA",
            "boats": [],
        }

    return {
        "status": "READY_FOR_VALIDATION",
        "reason": "STRUCTURED_DATA_EXTRACTED",
        "boats": boats,
    }


if __name__ == "__main__":
    print(
        "RACER_DATA_PARSER_READY",
        "MOCK_HTML_ONLY",
    )
