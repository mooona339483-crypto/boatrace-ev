import unittest
from itertools import permutations

from ai_integration import (
    evaluate_integration,
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
):
    rows = []

    for number in range(
        1,
        boat_count + 1,
    ):
        values = {
            "艇番":
                str(number),
            "全国勝率":
                str(
                    round(
                        7.5
                        - number * 0.3,
                        2,
                    )
                ),
            "モーター2連対率":
                str(
                    50
                    - number * 2
                ),
            "展示タイム":
                str(
                    round(
                        6.60
                        + number * 0.03,
                        2,
                    )
                ),
            "平均ST":
                str(
                    round(
                        0.10
                        + number * 0.01,
                        2,
                    )
                ),
            "進入コース":
                str(number),
        }

        row = (
            "<tr>"
            + "".join(
                f"<td>{values[h]}</td>"
                for h in HEADERS
            )
            + "</tr>"
        )

        rows.append(row)

    header = (
        "<tr>"
        + "".join(
            f"<th>{h}</th>"
            for h in HEADERS
        )
        + "</tr>"
    )

    return (
        "<table>"
        + header
        + "".join(rows)
        + "</table>"
    )


def make_odds_map(
    boat_count,
    bet_type,
):
    numbers = list(
        range(
            1,
            boat_count + 1,
        )
    )

    count = (
        2
        if bet_type == "2T"
        else 3
    )

    odds = (
        10.0
        if bet_type == "2T"
        else 30.0
    )

    return {
        "-".join(
            map(
                str,
                outcome,
            )
        ): odds
        for outcome in permutations(
            numbers,
            count,
        )
    }


def make_odds_maps(
    boat_count,
):
    return {
        "2T": make_odds_map(
            boat_count,
            "2T",
        ),
        "3T": make_odds_map(
            boat_count,
            "3T",
        ),
    }


class TestAIIntegration(
    unittest.TestCase
):

    def test_female_race_skipped(
        self,
    ):
        result = evaluate_integration(
            html=make_html(6),
            odds_maps=(
                make_odds_maps(6)
            ),
            race_category="female",
            actual_course_verified=True,
            model_verified=False,
        )

        self.assertEqual(
            result["status"],
            "SKIP",
        )

        self.assertEqual(
            result["reason"],
            "FEMALE_ONLY_RACE",
        )

    def test_course_not_verified(
        self,
    ):
        result = evaluate_integration(
            html=make_html(6),
            odds_maps=(
                make_odds_maps(6)
            ),
            race_category="mixed",
            actual_course_verified=False,
            model_verified=False,
        )

        self.assertEqual(
            result["status"],
            "SKIP",
        )

        self.assertEqual(
            result["reason"],
            "COURSE_NOT_VERIFIED",
        )

    def test_unverified_model_has_no_bets(
        self,
    ):
        result = evaluate_integration(
            html=make_html(6),
            odds_maps=(
                make_odds_maps(6)
            ),
            race_category="mixed",
            actual_course_verified=True,
            model_verified=False,
        )

        self.assertEqual(
            result["status"],
            "UNVERIFIED_CANDIDATES",
        )

        self.assertFalse(
            result["verified"]
        )

        self.assertEqual(
            result["decisions"]["2T"],
            [],
        )

        self.assertEqual(
            result["decisions"]["3T"],
            [],
        )

    def test_six_boat_candidate_count(
        self,
    ):
        result = evaluate_integration(
            html=make_html(6),
            odds_maps=(
                make_odds_maps(6)
            ),
            race_category="mixed",
            actual_course_verified=True,
            model_verified=False,
        )

        candidates = (
            result["candidates"]
        )

        two_t = [
            item
            for item in candidates
            if item.bet_type == "2T"
        ]

        three_t = [
            item
            for item in candidates
            if item.bet_type == "3T"
        ]

        self.assertEqual(
            len(two_t),
            30,
        )

        self.assertEqual(
            len(three_t),
            120,
        )

    def test_five_boat_candidate_count(
        self,
    ):
        result = evaluate_integration(
            html=make_html(5),
            odds_maps=(
                make_odds_maps(5)
            ),
            race_category="mixed",
            actual_course_verified=True,
            model_verified=False,
        )

        candidates = (
            result["candidates"]
        )

        two_t = [
            item
            for item in candidates
            if item.bet_type == "2T"
        ]

        three_t = [
            item
            for item in candidates
            if item.bet_type == "3T"
        ]

        self.assertEqual(
            len(two_t),
            20,
        )

        self.assertEqual(
            len(three_t),
            60,
        )

    def test_incomplete_odds_skipped(
        self,
    ):
        result = evaluate_integration(
            html=make_html(6),
            odds_maps={
                "2T": {
                    "1-2": 10.0,
                },
                "3T": {
                    "1-2-3": 30.0,
                },
            },
            race_category="mixed",
            actual_course_verified=True,
            model_verified=False,
        )

        self.assertEqual(
            result["status"],
            "SKIP",
        )

        self.assertEqual(
            result["reason"],
            "NO_COMPLETE_DATA",
        )

    def test_unknown_category_skipped(
        self,
    ):
        result = evaluate_integration(
            html=make_html(6),
            odds_maps=(
                make_odds_maps(6)
            ),
            race_category="unknown",
            actual_course_verified=True,
            model_verified=False,
        )

        self.assertEqual(
            result["status"],
            "SKIP",
        )

        self.assertEqual(
            result["reason"],
            "UNKNOWN_RACE_CATEGORY",
        )

    def test_candidate_probabilities_valid(
        self,
    ):
        result = evaluate_integration(
            html=make_html(6),
            odds_maps=(
                make_odds_maps(6)
            ),
            race_category="mixed",
            actual_course_verified=True,
            model_verified=False,
        )

        for candidate in (
            result["candidates"]
        ):
            self.assertGreater(
                candidate.probability,
                0,
            )

            self.assertLessEqual(
                candidate.probability,
                1,
            )

            self.assertGreater(
                candidate.odds,
                1,
            )


if __name__ == "__main__":
    unittest.main()
