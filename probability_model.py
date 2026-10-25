
from dataclasses import dataclass
from itertools import permutations
from math import exp, isfinite


@dataclass(frozen=True)
class Boat:
    number: int
    racer_win_rate: float
    motor_2rate: float
    exhibition_time: float
    average_st: float
    course: int


WEIGHTS = {
    "racer": 0.50,
    "motor": 0.20,
    "exhibition": 0.15,
    "start": 0.10,
    "course": 0.05,
}


def normalize(values, reverse=False):
    if any(not isfinite(v) for v in values):
        raise ValueError("Non-finite input")

    low = min(values)
    high = max(values)

    if high == low:
        return [0.5] * len(values)

    result = [(v - low) / (high - low) for v in values]

    if reverse:
        result = [1 - v for v in result]

    return result


def calculate_strengths(boats):
    if len(boats) not in (5, 6):
        raise ValueError("Expected 5 or 6 boats")

    numbers = [b.number for b in boats]
    courses = [b.course for b in boats]

    if (
        len(set(numbers)) != len(boats)
        or len(set(courses)) != len(boats)
        or any(not 1 <= n <= 6 for n in numbers)
        or any(not 1 <= c <= 6 for c in courses)
    ):
        raise ValueError("Invalid boats or courses")

    features = {
        "racer": normalize([b.racer_win_rate for b in boats]),
        "motor": normalize([b.motor_2rate for b in boats]),
        "exhibition": normalize(
            [b.exhibition_time for b in boats],
            reverse=True,
        ),
        "start": normalize(
            [b.average_st for b in boats],
            reverse=True,
        ),
        "course": normalize(
            [b.course for b in boats],
            reverse=True,
        ),
    }

    strengths = {}

    for i, boat in enumerate(boats):
        score = sum(
            WEIGHTS[key] * features[key][i]
            for key in WEIGHTS
        )
        strengths[boat.number] = exp(score)

    return strengths


def predict_probabilities(boats, bet_type="3T"):
    if bet_type not in ("2T", "3T"):
        raise ValueError("Invalid bet type")

    strengths = calculate_strengths(boats)

    count = 2 if bet_type == "2T" else 3
    probabilities = {}

    for outcome in permutations(strengths, count):
        remaining = sum(strengths.values())
        probability = 1.0

        for boat_number in outcome:
            strength = strengths[boat_number]
            probability *= strength / remaining
            remaining -= strength

        selection = "-".join(map(str, outcome))
        probabilities[selection] = probability

    total = sum(probabilities.values())

    if total <= 0 or not isfinite(total):
        raise ValueError("Invalid probability total")

    return {
        key: value / total
        for key, value in probabilities.items()
    }


def evaluate_race(boats, odds_map, bet_type="3T"):
    from ev_engine import evaluate_ev

    probabilities = predict_probabilities(boats, bet_type)

    results = []

    for selection, odds in odds_map.items():
        if selection not in probabilities:
            continue

        result = evaluate_ev(
            selection=selection,
            odds=odds,
            probability=probabilities[selection],
            verified=False,
        )
        results.append(result)

    return results


if __name__ == "__main__":
    print(
        "PROBABILITY_MODEL_READY",
        "UNVERIFIED",
    )
