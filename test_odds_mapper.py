
import unittest

from odds_mapper import (
    map_2t,
    map_3t,
    expand_grid,
)


def make_html(bet_type, boat_count=6):
    if bet_type == "2T":
        marker = "2連単オッズ"
        columns_per_boat = 2
    elif bet_type == "3T":
        marker = "3連単オッズ"
        columns_per_boat = 3
    else:
        raise ValueError("Invalid bet type")

    rows = []

    for second in range(1, boat_count + 1):
        cells = []

        for first in range(1, 7):
            if bet_type == "2T":
                odds = (
                    10 * first + second / 10
                    if first != second and first <= boat_count
                    else "-"
                )

                cells.extend([
                    str(second),
                    str(odds),
                ])

            else:
                third = (
                    second % boat_count
                ) + 1

                odds = (
                    100 * first + 10 * second + third
                    if len({first, second, third}) == 3
                    and first <= boat_count
                    else "-"
                )

                cells.extend([
                    str(second),
                    str(third),
                    str(odds),
                ])

        rows.append(
            "<tr>"
            + "".join(
                f"<td>{value}</td>" for value in cells
            )
            + "</tr>"
        )

    return (
        marker
        + "<table>"
        + "".join(rows)
        + "</table>"
    )


class TestOddsMapper(unittest.TestCase):

    def test_2t_valid_selections(self):
        html = make_html("2T")
        result = map_2t(html)

        self.assertIn("1-2", result)
        self.assertNotIn("1-1", result)

    def test_2t_odds_correspondence(self):
        html = make_html("2T")
        result = map_2t(html)

        self.assertAlmostEqual(
            result["1-2"],
            10.2,
        )
        self.assertAlmostEqual(
            result["3-5"],
            30.5,
        )

    def test_3t_valid_selections(self):
        html = make_html("3T")
        result = map_3t(html)

        self.assertIn("1-2-3", result)
        self.assertNotIn("1-1-3", result)

    def test_3t_odds_correspondence(self):
        html = make_html("3T")
        result = map_3t(html)

        self.assertEqual(
            result["1-2-3"],
            123.0,
        )

    def test_missing_table_2t(self):
        self.assertEqual(
            map_2t("<html>No table</html>"),
            {},
        )

    def test_missing_table_3t(self):
        self.assertEqual(
            map_3t("<html>No table</html>"),
            {},
        )

    def test_2t_five_boats_no_six(self):
        html = make_html("2T", 5)
        result = map_2t(html)

        self.assertTrue(
            all(
                "6" not in key.split("-")
                for key in result
            )
        )

    def test_expand_grid_basic(self):
        rows = [
            [
                {
                    "text": "1",
                    "rowspan": 1,
                    "colspan": 1,
                },
                {
                    "text": "2",
                    "rowspan": 1,
                    "colspan": 1,
                },
            ]
        ]

        self.assertEqual(
            expand_grid(rows),
            [["1", "2"]],
        )


if __name__ == "__main__":
    unittest.main()
