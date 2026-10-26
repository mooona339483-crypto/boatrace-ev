from dataclasses import dataclass
from math import isfinite

from racer_data_parser import (
    evaluate_data_readiness,
)
from probability_model import (
    Boat,
    predict_probabilities,
)
from bet_manager import (
    BetCandidate,
    select_bets,
)


BET_TYPES = (
    "2T",
    "3T",
)


@dataclass(frozen=True)
class PredictionCandidate:
    bet_type: str
    selection: str
    probability: float
    odds: float
    ev: float
    verified: bool


def skip(reason):
    return {
        "status": "SKIP",
        "reason": reason,
        "candidates": [],
        "decisions": {
            "2T": [],
            "3T": [],
        },
        "verified": False,
    }


def normalize_race_category(
    race_category,
):
    if race_category in (
        "female",
        "female_only",
    ):
        return "female_only"

    if race_category == "male":
        return "male"

    if race_category == "mixed":
        return "mixed"

    return None


def convert_boats(
    parsed_boats,
):
    return [
        Boat(
            number=boat.number,
            racer_win_rate=(
                boat.racer_win_rate
            ),
            motor_2rate=(
                boat.motor_2rate
            ),
            exhibition_time=(
                boat.exhibition_time
            ),
            average_st=(
                boat.average_st
            ),
            course=boat.course,
        )
        for boat in parsed_boats
    ]


def validate_odds_map(
    odds_map,
    probabilities,
):
    if not isinstance(
        odds_map,
        dict,
    ):
        return False

    if (
        set(odds_map)
        != set(probabilities)
    ):
        return False

    for (
        selection,
        odds,
    ) in odds_map.items():

        if (
            not isinstance(
                selection,
                str,
            )
            or not isinstance(
                odds,
                (int, float),
            )
            or isinstance(
                odds,
                bool,
            )
            or not isfinite(odds)
            or odds <= 1
        ):
            return False

    return True


def build_candidates(
    boats,
    odds_map,
    bet_type,
    *,
    model_verified,
):
    probabilities = (
        predict_probabilities(
            boats,
            bet_type,
        )
    )

    if not validate_odds_map(
        odds_map,
        probabilities,
    ):
        raise ValueError(
            "Incomplete odds map"
        )

    candidates = []

    for (
        selection,
        probability,
    ) in probabilities.items():

        odds = odds_map[
            selection
        ]

        ev = (
            probability
            * odds
            - 1
        )

        candidates.append(
            PredictionCandidate(
                bet_type=bet_type,
                selection=selection,
                probability=round(
                    probability,
                    8,
                ),
                odds=odds,
                ev=round(
                    ev,
                    6,
                ),
                verified=(
                    model_verified
                    is True
                ),
            )
        )

    candidates.sort(
        key=lambda item: (
            -item.ev,
            -item.probability,
            item.selection,
        )
    )

    return candidates


def convert_to_bet_candidates(
    candidates,
):
    return [
        BetCandidate(
            selection=(
                item.selection
            ),
            probability=(
                item.probability
            ),
            odds=item.odds,
            verified=(
                item.verified
            ),
        )
        for item in candidates
    ]


def evaluate_integration(
    html,
    odds_maps,
    race_category="mixed",
    *,
    actual_course_verified=False,
    model_verified=False,
):
    category = (
        normalize_race_category(
            race_category
        )
    )

    if category is None:
        return skip(
            "UNKNOWN_RACE_CATEGORY"
        )

    if category == "female_only":
        return skip(
            "FEMALE_ONLY_RACE"
        )

    # 実際の進入コースが
    # 確認できない場合は見送る
    if actual_course_verified is not True:
        return skip(
            "COURSE_NOT_VERIFIED"
        )

    data = (
        evaluate_data_readiness(
            html
        )
    )

    if (
        data["status"]
        != "READY_FOR_VALIDATION"
    ):
        return skip(
            data["reason"]
        )

    try:
        boats = convert_boats(
            data["boats"]
        )

    except (
        TypeError,
        ValueError,
        AttributeError,
    ):
        return skip(
            "INVALID_BOAT_DATA"
        )

    if not isinstance(
        odds_maps,
        dict,
    ):
        return skip(
            "INVALID_ODDS_MAP"
        )

    all_candidates = []
    decisions = {
        "2T": [],
        "3T": [],
    }

    for bet_type in BET_TYPES:

        odds_map = odds_maps.get(
            bet_type
        )

        if not isinstance(
            odds_map,
            dict,
        ):
            continue

        try:
            candidates = (
                build_candidates(
                    boats=boats,
                    odds_map=odds_map,
                    bet_type=bet_type,
                    model_verified=(
                        model_verified
                    ),
                )
            )

        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            continue

        all_candidates.extend(
            candidates
        )

        bet_candidates = (
            convert_to_bet_candidates(
                candidates
            )
        )

        try:
            decisions[
                bet_type
            ] = select_bets(
                bet_type=bet_type,
                candidates=(
                    bet_candidates
                ),
                race_category=(
                    category
                ),
            )

        except ValueError:
            decisions[
                bet_type
            ] = []

    if not all_candidates:
        return skip(
            "NO_COMPLETE_DATA"
        )

    all_candidates.sort(
        key=lambda item: (
            -item.ev,
            -item.probability,
            item.bet_type,
            item.selection,
        )
    )

    if model_verified is not True:
        return {
            "status":
                "UNVERIFIED_CANDIDATES",
            "reason":
                "MODEL_NOT_VERIFIED",
            "candidates":
                all_candidates,
            "decisions": {
                "2T": [],
                "3T": [],
            },
            "verified":
                False,
        }

    total_decisions = (
        len(
            decisions["2T"]
        )
        + len(
            decisions["3T"]
        )
    )

    if total_decisions == 0:
        return {
            "status":
                "SKIP",
            "reason":
                "NO_POSITIVE_EV_BETS",
            "candidates":
                all_candidates,
            "decisions":
                decisions,
            "verified":
                True,
        }

    return {
        "status":
            "VIRTUAL_CANDIDATES",
        "reason":
            "PASSED_FILTERS",
        "candidates":
            all_candidates,
        "decisions":
            decisions,
        "verified":
            True,
    }


if __name__ == "__main__":
    print(
        "AI_INTEGRATION_READY",
        "NO_REAL_BETS",
    )
