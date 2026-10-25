
import unittest

from bet_manager import (
    BetCandidate,
    select_bets,
    summarize_bets,
    BUDGET_PER_TYPE,
)


def candidate(
    selection="1-2-3",
    probability=0.10,
    odds=15.0,
    verified=True,
):
    return BetCandidate(
        selection=selection,
        probability=probability,
        odds=odds,
        verified=verified,
    )


class TestBetManager(unittest.TestCase):

    def test_unverified_skipped(self):
        result = select_bets(
            "3T",
            [candidate(verified=False)],
        )
        self.assertEqual(result, [])

    def test_female_only_excluded(self):
        result = select_bets(
            "3T",
            [candidate()],
            race_category="female_only",
        )
        self.assertEqual(result, [])

    def test_low_probability_skipped(self):
        result = select_bets(
            "3T",
            [candidate(probability=0.05, odds=30.0)],
        )
        self.assertEqual(result, [])

    def test_low_ev_skipped(self):
        result = select_bets(
            "3T",
            [candidate(probability=0.10, odds=5.0)],
        )
        self.assertEqual(result, [])

    def test_valid_3t_candidate(self):
        result = select_bets(
            "3T",
            [candidate()],
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].stake, 10000)
        self.assertEqual(
            result[0].decision,
            "VIRTUAL_CANDIDATE",
        )
        self.assertAlmostEqual(result[0].ev, 0.50)

    def test_budget_limit_rejected(self):
        with self.assertRaises(ValueError):
            select_bets(
                "3T",
                [candidate()],
                budget=10100,
            )

    def test_duplicate_selection_rejected(self):
        with self.assertRaises(ValueError):
            select_bets(
                "3T",
                [candidate(), candidate()],
            )

    def test_invalid_selection_rejected(self):
        with self.assertRaises(ValueError):
            select_bets(
                "3T",
                [candidate(selection="1-1-3")],
            )

    def test_budget_split(self):
        result = select_bets(
            "3T",
            [
                candidate("1-2-3"),
                candidate("1-3-2"),
            ],
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(
            sum(item.stake for item in result),
            BUDGET_PER_TYPE,
        )
        self.assertTrue(
            all(item.stake % 100 == 0 for item in result)
        )

    def test_separate_bet_type_totals(self):
        two_t = select_bets(
            "2T",
            [candidate("1-2", 0.15, 10.0)],
        )
        three_t = select_bets(
            "3T",
            [candidate()],
        )

        totals = summarize_bets(two_t + three_t)

        self.assertEqual(totals["2T"], 10000)
        self.assertEqual(totals["3T"], 10000)


if __name__ == "__main__":
    unittest.main()
