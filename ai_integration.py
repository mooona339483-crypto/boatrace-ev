
from dataclasses import dataclass
from math import isfinite

from racer_data_parser import evaluate_data_readiness
from probability_model import (
    Boat,
    predict_probabilities,
)


BET_TYPES = ("2T", "3T")


@dataclass(frozen=True)
class PredictionCandidate:
    bet_type: str
    selection: str
    probability: float
    odds: float
    ev: float


def skip(reason):
    return {
        "status": "SKIP",
        "reason": reason,
        "candidates": [],
        "verified": False,
    }


def convert_boats(parsed_boats):
    return [
        Boat(
            number=b.number,
            racer_win_rate=b.racer_win_rate,
            motor_2rate=b.motor_2rate,
            exhibition_time=b.exhibition_time,
            average_st=b.average_st,
            course=b.course,
        )
        for b in parsed_boats
    ]


def evaluate_integration(
    html,
    odds_maps,
    race_category="mixed",
    *,
    actual_course_verified=False,
):
    # Never place or record a bet here.
    # This function only evaluates test candidates.

    if race_category == "female_only":
        return skip("FEMALE_ONLY_RACE")

    if race_category not in ("male", "mixed"):
        return skip("UNKNOWN_RACE_CATEGORY")

    # Do not use boat number as an assumed course.
    if actual_course_verified is not True:
        return skip("COURSE_NOT_VERIFIED")

    data = evaluate_data_readiness(html)

    if data["status"] != "READY_FOR_VALIDATION":
        return skip(data["reason"])

    try:
        boats = convert_boats(data["boats"])
    except (TypeError, ValueError, AttributeError):
        return skip("INVALID_BOAT_DATA")

    if not isinstance(odds_maps, dict):
        return skip("INVALID_ODDS_MAP")

    results = []

    for bet_type in BET_TYPES:
        odds_map = odds_maps.get(bet_type)

        if not isinstance(odds_map, dict):
            continue

        try:
            probabilities = predict_probabilities(
                boats,
                bet_type,
            )
        except (TypeError, ValueError, OverflowError):
            return skip("PROBABILITY_MODEL_ERROR")

        expected_count = (
            len(boats) * (len(boats) - 1)
            if bet_type == "2T"
            else len(boats)
            * (len(boats) - 1)
            * (len(boats) - 2)
        )

        if len(probabilities) != expected_count:
            return skip("INCOMPLETE_PROBABILITIES")

        if set(odds_map) != set(probabilities):
            return skip("INCOMPLETE_ODDS")

        for selection, probability in probabilities.items():
            odds = odds_map[selection]

            if (
                not isinstance(probability, (int, float))
                or isinstance(probability, bool)
                or not isfinite(probability)
                or not 0 < probability <= 1
                or not isinstance(odds, (int, float))
                or isinstance(odds, bool)
                or not isfinite(odds)
                or odds <= 1
            ):
                return skip("INVALID_PROBABILITY_OR_ODDS")

            ev = probability * odds - 1

            results.append(
                PredictionCandidate(
                    bet_type=bet_type,
                    selection=selection,
                    probability=probability,
                    odds=odds,
                    ev=ev,
                )
            )

    if not results:
        return skip("NO_COMPLETE_ODDS_DATA")

    results.sort(
        key=lambda item: (
            -item.ev,
            -item.probability,
            item.bet_type,
            item.selection,
        )
    )

    return {
        "status": "UNVERIFIED_CANDIDATES",
        "reason": "MOCK_VALIDATION_ONLY",
        "candidates": results,
        "verified": False,
    }


if __name__ == "__main__":
    print(
        "AI_INTEGRATION_READY",
        "NO_BETS_PLACED",
        "NO_PREDICTIONS_RECORDED",
    )
