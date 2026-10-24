
import unittest
from math import isclose

from probability_model import (
    Boat,
    predict_probabilities,
    evaluate_race,
)


def make_boats(count=6):
    return [
        Boat(
            number=i,
            racer_win_rate=5.0 + i * 0.3,
            motor_2rate=30.0 + i,
            exhibition_time=6.90 - i * 0.02,
            average_st=0.18 - i * 0.01,
            course=i,
        )
        for i in range(1, count + 1)
    ]


class TestProbabilityModel(unittest.TestCase):

    def test_6boats_2t(self):
        result = predict_probabilities(
            make_boats(6), "2T"
        )
        self.assertEqual(len(result), 30)
        self.assertTrue(
            isclose(sum(result.values()), 1.0, abs_tol=1e-10)
        )

    def test_6boats_3t(self):
        result = predict_probabilities(
            make_boats(6), "3T"
        )
        self.assertEqual(len(result), 120)
        self.assertTrue(
            isclose(sum(result.values()), 1.0, abs_tol=1e-10)
        )

    def test_5boats_2t(self):
        result = predict_probabilities(
            make_boats(5), "2T"
        )
        self.assertEqual(len(result), 20)
        self.assertTrue(
            isclose(sum(result.values()), 1.0, abs_tol=1e-10)
        )

    def test_5boats_3t(self):
        result = predict_probabilities(
            make_boats(5), "3T"
        )
        self.assertEqual(len(result), 60)
        self.assertTrue(
            isclose(sum(result.values()), 1.0, abs_tol=1e-10)
        )

    def test_probabilities_in_valid_range(self):
        result = predict_probabilities(
            make_boats(6), "3T"
        )
        self.assertTrue(
            all(0 <= p <= 1 for p in result.values())
        )

    def test_duplicate_boats_rejected(self):
        boats = make_boats(6)
        boats[1] = Boat(
            number=1,
            racer_win_rate=6.0,
            motor_2rate=35.0,
            exhibition_time=6.80,
            average_st=0.15,
            course=2,
        )
        with self.assertRaises(ValueError):
            predict_probabilities(boats, "3T")

    def test_invalid_bet_type_rejected(self):
        with self.assertRaises(ValueError):
            predict_probabilities(make_boats(6), "WIN")

    def test_unverified_model_skips(self):
        results = evaluate_race(
            make_boats(6),
            {"1-2-3": 20.0},
            "3T",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].decision, "SKIP")
        self.assertIsNone(results[0].ev)


if __name__ == "__main__":
    unittest.main()
