
import unittest

from ev_engine import evaluate_ev


class TestEVEngine(unittest.TestCase):

    def test_unverified_probability_is_skipped(self):
        result = evaluate_ev(
            "1-2-3",
            odds=15.0,
            probability=0.20,
            verified=False,
        )
        self.assertEqual(result.decision, "SKIP")
        self.assertIsNone(result.ev)

    def test_missing_probability_is_skipped(self):
        result = evaluate_ev(
            "1-2-3",
            odds=15.0,
            probability=None,
            verified=True,
        )
        self.assertEqual(result.decision, "SKIP")

    def test_low_probability_is_skipped(self):
        result = evaluate_ev(
            "1-2-3",
            odds=20.0,
            probability=0.05,
            verified=True,
        )
        self.assertEqual(result.decision, "SKIP")

    def test_low_ev_is_skipped(self):
        result = evaluate_ev(
            "1-2-3",
            odds=5.0,
            probability=0.10,
            verified=True,
        )
        self.assertEqual(result.decision, "SKIP")

    def test_positive_ev_candidate(self):
        result = evaluate_ev(
            "1-2-3",
            odds=15.0,
            probability=0.10,
            verified=True,
        )
        self.assertEqual(result.decision, "CANDIDATE")
        self.assertAlmostEqual(result.ev, 0.50)

    def test_invalid_probability(self):
        with self.assertRaises(ValueError):
            evaluate_ev(
                "1-2-3",
                odds=10.0,
                probability=1.5,
                verified=True,
            )


if __name__ == "__main__":
    unittest.main()
