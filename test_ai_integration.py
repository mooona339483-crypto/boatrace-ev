
import unittest
from unittest.mock import patch

from ai_integration import evaluate_integration
from probability_model import Boat, predict_probabilities


HEADERS = [
    "艇番",
    "全国勝率",
    "モーター2連対率",
    "展示タイム",
    "平均ST",
    "進入コース",
]


def make_html(boat_count=6, missing=False):
    rows = []

    for number in range(1, boat_count + 1):
        values = [
            str(number),
            f"{5.0 + number * 0.3:.2f}",
            f"{30 + number:.1f}%",
            f"{6.90 - number * 0.02:.2f}",
            f"{0.20 - number * 0.01:.2f}",
            str(number),
        ]

        if missing and number == 1:
            values[4] = "-"

        rows.append(
            "<tr>"
            + "".join(
                f"<td>{v}</td>" for v in values
            )
            + "</tr>"
        )

    return (
        "<table><tr>"
        + "".join(f"<th>{h}</th>" for h in HEADERS)
        + "</tr>"
        + "".join(rows)
        + "</table>"
    )


def make_boats(boat_count=6):
    return [
        Boat(
            number=n,
            racer_win_rate=5.0 + n * 0.3,
            motor_2rate=30.0 + n,
            exhibition_time=round(6.90 - n * 0.02, 2),
            average_st=round(0.20 - n * 0.01, 2),
            course=n,
        )
        for n in range(1, boat_count + 1)
    ]


def make_odds_maps(boat_count=6):
    boats = make_boats(boat_count)

    return {
        bet_type: {
            selection: 20.0 if bet_type == "2T"
            else 100.0
            for selection in predict_probabilities(
                boats, bet_type
            )
        }
        for bet_type in ("2T", "3T")
    }


class TestAIIntegration(unittest.TestCase):

    def setUp(self):
        self.html = make_html()
        self.odds_maps = make_odds_maps()

    def evaluate(self, **changes):
        params = {
            "html": self.html,
            "odds_maps": self.odds_maps,
            "race_category": "mixed",
            "actual_course_verified": True,
        }
        params.update(changes)
        return evaluate_integration(**params)

    def test_course_not_verified(self):
        result = self.evaluate(
            actual_course_verified=False
        )
        self.assertEqual(result["status"], "SKIP")
        self.assertEqual(
            result["reason"],
            "COURSE_NOT_VERIFIED",
        )

    def test_female_only_skipped(self):
        result = self.evaluate(
            race_category="female_only"
        )
        self.assertEqual(result["status"], "SKIP")

    def test_unknown_category_skipped(self):
        result = self.evaluate(
            race_category="unknown"
        )
        self.assertEqual(result["status"], "SKIP")

    def test_missing_racer_data_skipped(self):
        result = self.evaluate(
            html=make_html(missing=True)
        )
        self.assertEqual(result["status"], "SKIP")

    def test_invalid_odds_map_skipped(self):
        result = self.evaluate(odds_maps=None)
        self.assertEqual(
            result["reason"],
            "INVALID_ODDS_MAP",
        )

    def test_incomplete_odds_skipped(self):
        result = self.evaluate(
            odds_maps={
                "2T": {"1-2": 10.0},
                "3T": {},
            }
        )
        self.assertEqual(
            result["reason"],
            "INCOMPLETE_ODDS",
        )

    def test_both_bet_types(self):
        result = self.evaluate()

        self.assertEqual(
            result["status"],
            "UNVERIFIED_CANDIDATES",
        )
        self.assertEqual(
            len(result["candidates"]),
            150,
        )
        self.assertEqual(
            {
                c.bet_type
                for c in result["candidates"]
            },
            {"2T", "3T"},
        )

    def test_ev_calculation(self):
        result = self.evaluate()

        self.assertEqual(
            result["status"],
            "UNVERIFIED_CANDIDATES",
        )

        for item in result["candidates"]:
            self.assertAlmostEqual(
                item.ev,
                item.probability * item.odds - 1,
            )

    def test_ev_sorted(self):
        result = self.evaluate()
        values = [
            item.ev
            for item in result["candidates"]
        ]
        self.assertEqual(
            values,
            sorted(values, reverse=True),
        )

    def test_no_verified_bets(self):
        result = self.evaluate()
        self.assertIs(result["verified"], False)
        self.assertEqual(
            result["reason"],
            "MOCK_VALIDATION_ONLY",
        )

    def test_five_boats(self):
        result = self.evaluate(
            html=make_html(5),
            odds_maps=make_odds_maps(5),
        )
        self.assertEqual(
            result["status"],
            "UNVERIFIED_CANDIDATES",
        )
        self.assertEqual(
            len(result["candidates"]),
            80,
        )

    def test_no_odds_skipped(self):
        result = self.evaluate(odds_maps={})
        self.assertEqual(
            result["reason"],
            "NO_COMPLETE_ODDS_DATA",
        )

    def test_model_error_skipped(self):
        with patch(
            "ai_integration.predict_probabilities",
            side_effect=ValueError("test error"),
        ):
            result = self.evaluate()

        self.assertEqual(
            result["reason"],
            "PROBABILITY_MODEL_ERROR",
        )


if __name__ == "__main__":
    unittest.main()
