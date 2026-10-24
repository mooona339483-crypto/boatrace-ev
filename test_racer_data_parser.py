
import unittest

from racer_data_parser import (
    parse_racer_data,
    evaluate_data_readiness,
)


HEADERS = [
    "艇番",
    "全国勝率",
    "モーター2連対率",
    "展示タイム",
    "平均ST",
    "進入コース",
]


def make_html(
    boat_count=6,
    missing=None,
    duplicate=False,
    invalid=None,
):
    rows = []

    for number in range(1, boat_count + 1):
        boat_number = (
            1 if duplicate and number == 2
            else number
        )

        values = {
            "艇番": str(boat_number),
            "全国勝率": "6.50",
            "モーター2連対率": "38.5%",
            "展示タイム": "6.80",
            "平均ST": "0.15",
            "進入コース": str(number),
        }

        if missing and number == 1:
            values[missing] = "-"

        if invalid and number == 1:
            field, value = invalid
            values[field] = value

        rows.append(
            "<tr>"
            + "".join(
                f"<td>{values[h]}</td>"
                for h in HEADERS
            )
            + "</tr>"
        )

    return (
        "<table><tr>"
        + "".join(
            f"<th>{h}</th>" for h in HEADERS
        )
        + "</tr>"
        + "".join(rows)
        + "</table>"
    )


class TestRacerDataParser(unittest.TestCase):

    def test_six_boats(self):
        boats = parse_racer_data(make_html(6))
        self.assertEqual(len(boats), 6)

    def test_five_boats(self):
        boats = parse_racer_data(make_html(5))
        self.assertEqual(len(boats), 5)

    def test_win_rate(self):
        boats = parse_racer_data(make_html())
        self.assertAlmostEqual(
            boats[0].racer_win_rate, 6.50
        )

    def test_motor_rate(self):
        boats = parse_racer_data(make_html())
        self.assertAlmostEqual(
            boats[0].motor_2rate, 38.5
        )

    def test_exhibition_and_st(self):
        boats = parse_racer_data(make_html())
        self.assertAlmostEqual(
            boats[0].exhibition_time, 6.80
        )
        self.assertAlmostEqual(
            boats[0].average_st, 0.15
        )

    def test_missing_value_skipped(self):
        result = evaluate_data_readiness(
            make_html(missing="平均ST")
        )
        self.assertEqual(result["status"], "SKIP")

    def test_duplicate_boat_rejected(self):
        result = evaluate_data_readiness(
            make_html(duplicate=True)
        )
        self.assertEqual(result["status"], "SKIP")

    def test_invalid_win_rate_skipped(self):
        result = evaluate_data_readiness(
            make_html(
                invalid=("全国勝率", "15.0")
            )
        )
        self.assertEqual(result["status"], "SKIP")

    def test_invalid_course_skipped(self):
        result = evaluate_data_readiness(
            make_html(
                invalid=("進入コース", "7")
            )
        )
        self.assertEqual(result["status"], "SKIP")

    def test_ready_status(self):
        result = evaluate_data_readiness(
            make_html(6)
        )
        self.assertEqual(
            result["status"],
            "READY_FOR_VALIDATION",
        )
        self.assertEqual(len(result["boats"]), 6)


if __name__ == "__main__":
    unittest.main()
