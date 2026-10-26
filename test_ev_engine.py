import unittest

from ev_engine import (
    evaluate_ev,
    evaluate_many,
)


class TestEVEngine(unittest.TestCase):

    def test_unverified_is_skip(self):
        result = evaluate_ev(
            selection="1-2-3",
            odds=20.0,
            probability=0.10,
            verified=False,
            bet_type="3T",
        )

        self.assertEqual(
            result.decision,
            "SKIP",
        )

        self.assertIsNone(
            result.ev,
        )

    def test_low_probability_2t_is_skip(self):
        result = evaluate_ev(
            selection="1-2",
            odds=20.0,
            probability=0.10,
            verified=True,
            bet_type="2T",
        )

        self.assertEqual(
            result.decision,
            "SKIP",
        )

        self.assertEqual(
            result.reason,
            "Low hit probability",
        )

    def test_low_probability_3t_is_skip(self):
        result = evaluate_ev(
            selection="1-2-3",
            odds=30.0,
            probability=0.07,
            verified=True,
            bet_type="3T",
        )

        self.assertEqual(
            result.decision,
            "SKIP",
        )

        self.assertEqual(
            result.reason,
            "Low hit probability",
        )

    def test_low_ev_is_skip(self):
        result = evaluate_ev(
            selection="1-2",
            odds=8.0,
            probability=0.13,
            verified=True,
            bet_type="2T",
        )

        self.assertEqual(
            result.decision,
            "SKIP",
        )

        self.assertEqual(
            result.reason,
            "Insufficient expected value",
        )

    def test_positive_ev_2t_is_candidate(self):
        result = evaluate_ev(
            selection="1-2",
            odds=10.0,
            probability=0.15,
            verified=True,
            bet_type="2T",
        )

        self.assertEqual(
            result.decision,
            "CANDIDATE",
        )

        self.assertAlmostEqual(
            result.ev,
            0.5,
            places=4,
        )

    def test_positive_ev_3t_is_candidate(self):
        result = evaluate_ev(
            selection="1-2-3",
            odds=20.0,
            probability=0.10,
            verified=True,
            bet_type="3T",
        )

        self.assertEqual(
            result.decision,
            "CANDIDATE",
        )

        self.assertAlmostEqual(
            result.ev,
            1.0,
            places=4,
        )

    def test_exact_min_probability_2t_allowed(self):
        result = evaluate_ev(
            selection="1-2",
            odds=10.0,
            probability=0.12,
            verified=True,
            bet_type="2T",
        )

        self.assertEqual(
            result.decision,
            "CANDIDATE",
        )

    def test_exact_min_probability_3t_allowed(self):
        result = evaluate_ev(
            selection="1-2-3",
            odds=15.0,
            probability=0.08,
            verified=True,
            bet_type="3T",
        )

        self.assertEqual(
            result.decision,
            "CANDIDATE",
        )

    def test_invalid_odds_rejected(self):
        with self.assertRaises(
            ValueError
        ):
            evaluate_ev(
                selection="1-2",
                odds=1.0,
                probability=0.20,
                verified=True,
                bet_type="2T",
            )

    def test_invalid_probability_rejected(self):
        with self.assertRaises(
            ValueError
        ):
            evaluate_ev(
                selection="1-2",
                odds=10.0,
                probability=1.5,
                verified=True,
                bet_type="2T",
            )

    def test_invalid_bet_type_rejected(self):
        with self.assertRaises(
            ValueError
        ):
            evaluate_ev(
                selection="1-2",
                odds=10.0,
                probability=0.20,
                verified=True,
                bet_type="WIN",
            )

    def test_evaluate_many_sorts_candidates_first(self):
        odds_map = {
            "1-2": 10.0,
            "1-3": 6.0,
            "2-1": 12.0,
        }

        probability_map = {
            "1-2": 0.15,
            "1-3": 0.10,
            "2-1": 0.13,
        }

        results = evaluate_many(
            bet_type="2T",
            odds_map=odds_map,
            probability_map=probability_map,
            verified=True,
        )

        self.assertEqual(
            results[0].decision,
            "CANDIDATE",
        )

        self.assertGreaterEqual(
            results[0].ev,
            results[1].ev,
        )

    def test_missing_probability_is_ignored(self):
        results = evaluate_many(
            bet_type="2T",
            odds_map={
                "1-2": 10.0,
                "1-3": 10.0,
            },
            probability_map={
                "1-2": 0.15,
            },
            verified=True,
        )

        self.assertEqual(
            len(results),
            1,
        )

        self.assertEqual(
            results[0].selection,
            "1-2",
        )


if __name__ == "__main__":
    unittest.main()
