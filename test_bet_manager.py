import unittest

from bet_manager import (
    BetCandidate,
    select_bets,
    summarize_bets,
)


class TestBetManager(unittest.TestCase):

    def test_unverified_candidates_are_skipped(self):
        result = select_bets(
            bet_type="3T",
            candidates=[
                BetCandidate(
                    selection="1-2-3",
                    probability=0.15,
                    odds=20.0,
                    verified=False,
                ),
            ],
            race_category="mixed",
        )

        self.assertEqual(
            result,
            [],
        )

    def test_female_only_race_is_skipped(self):
        result = select_bets(
            bet_type="2T",
            candidates=[
                BetCandidate(
                    selection="1-2",
                    probability=0.20,
                    odds=10.0,
                    verified=True,
                ),
            ],
            race_category="female_only",
        )

        self.assertEqual(
            result,
            [],
        )

    def test_low_probability_2t_is_skipped(self):
        result = select_bets(
            bet_type="2T",
            candidates=[
                BetCandidate(
                    selection="1-2",
                    probability=0.10,
                    odds=20.0,
                    verified=True,
                ),
            ],
        )

        self.assertEqual(
            result,
            [],
        )

    def test_low_probability_3t_is_skipped(self):
        result = select_bets(
            bet_type="3T",
            candidates=[
                BetCandidate(
                    selection="1-2-3",
                    probability=0.07,
                    odds=30.0,
                    verified=True,
                ),
            ],
        )

        self.assertEqual(
            result,
            [],
        )

    def test_low_ev_is_skipped(self):
        result = select_bets(
            bet_type="2T",
            candidates=[
                BetCandidate(
                    selection="1-2",
                    probability=0.13,
                    odds=8.0,
                    verified=True,
                ),
            ],
        )

        self.assertEqual(
            result,
            [],
        )

    def test_valid_2t_candidate_selected(self):
        result = select_bets(
            bet_type="2T",
            candidates=[
                BetCandidate(
                    selection="1-2",
                    probability=0.15,
                    odds=10.0,
                    verified=True,
                ),
            ],
        )

        self.assertEqual(
            len(result),
            1,
        )

        self.assertEqual(
            result[0].decision,
            "VIRTUAL_CANDIDATE",
        )

        self.assertEqual(
            result[0].stake,
            10000,
        )

    def test_valid_3t_candidate_selected(self):
        result = select_bets(
            bet_type="3T",
            candidates=[
                BetCandidate(
                    selection="1-2-3",
                    probability=0.10,
                    odds=20.0,
                    verified=True,
                ),
            ],
        )

        self.assertEqual(
            len(result),
            1,
        )

        self.assertEqual(
            result[0].stake,
            10000,
        )

    def test_total_budget_never_exceeds_10000(self):
        candidates = [
            BetCandidate(
                selection="1-2",
                probability=0.20,
                odds=10.0,
                verified=True,
            ),
            BetCandidate(
                selection="1-3",
                probability=0.18,
                odds=12.0,
                verified=True,
            ),
            BetCandidate(
                selection="2-1",
                probability=0.16,
                odds=14.0,
                verified=True,
            ),
        ]

        result = select_bets(
            bet_type="2T",
            candidates=candidates,
        )

        total = sum(
            item.stake
            for item in result
        )

        self.assertLessEqual(
            total,
            10000,
        )

        self.assertEqual(
            total,
            10000,
        )

    def test_all_stakes_are_100_yen_units(self):
        candidates = [
            BetCandidate(
                selection="1-2",
                probability=0.20,
                odds=10.0,
                verified=True,
            ),
            BetCandidate(
                selection="1-3",
                probability=0.18,
                odds=12.0,
                verified=True,
            ),
        ]

        result = select_bets(
            bet_type="2T",
            candidates=candidates,
        )

        self.assertTrue(
            all(
                item.stake % 100 == 0
                for item in result
            )
        )

    def test_2t_max_five_selections(self):
        selections = [
            "1-2",
            "1-3",
            "1-4",
            "1-5",
            "1-6",
            "2-1",
        ]

        candidates = [
            BetCandidate(
                selection=selection,
                probability=0.20,
                odds=10.0 + index,
                verified=True,
            )
            for index, selection
            in enumerate(selections)
        ]

        result = select_bets(
            bet_type="2T",
            candidates=candidates,
        )

        self.assertLessEqual(
            len(result),
            5,
        )

    def test_3t_max_eight_selections(self):
        selections = [
            "1-2-3",
            "1-2-4",
            "1-2-5",
            "1-2-6",
            "1-3-2",
            "1-3-4",
            "1-3-5",
            "1-3-6",
            "1-4-2",
        ]

        candidates = [
            BetCandidate(
                selection=selection,
                probability=0.10,
                odds=20.0 + index,
                verified=True,
            )
            for index, selection
            in enumerate(selections)
        ]

        result = select_bets(
            bet_type="3T",
            candidates=candidates,
        )

        self.assertLessEqual(
            len(result),
            8,
        )

    def test_duplicate_selection_rejected(self):
        candidates = [
            BetCandidate(
                selection="1-2",
                probability=0.20,
                odds=10.0,
                verified=True,
            ),
            BetCandidate(
                selection="1-2",
                probability=0.18,
                odds=12.0,
                verified=True,
            ),
        ]

        with self.assertRaises(
            ValueError
        ):
            select_bets(
                bet_type="2T",
                candidates=candidates,
            )

    def test_invalid_selection_rejected(self):
        with self.assertRaises(
            ValueError
        ):
            select_bets(
                bet_type="3T",
                candidates=[
                    BetCandidate(
                        selection="1-1-2",
                        probability=0.20,
                        odds=10.0,
                        verified=True,
                    ),
                ],
            )

    def test_budget_over_limit_rejected(self):
        with self.assertRaises(
            ValueError
        ):
            select_bets(
                bet_type="2T",
                candidates=[],
                budget=10100,
            )

    def test_summarize_bets(self):
        two_t = select_bets(
            bet_type="2T",
            candidates=[
                BetCandidate(
                    selection="1-2",
                    probability=0.20,
                    odds=10.0,
                    verified=True,
                ),
            ],
        )

        three_t = select_bets(
            bet_type="3T",
            candidates=[
                BetCandidate(
                    selection="1-2-3",
                    probability=0.10,
                    odds=20.0,
                    verified=True,
                ),
            ],
        )

        summary = summarize_bets(
            two_t + three_t
        )

        self.assertEqual(
            summary["2T"],
            10000,
        )

        self.assertEqual(
            summary["3T"],
            10000,
        )


if __name__ == "__main__":
    unittest.main()
