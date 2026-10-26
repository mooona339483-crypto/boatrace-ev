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
    if not values:
        raise ValueError("Empty values")

    if any(
        not isinstance(v, (int, float))
        or isinstance(v, bool)
        or not isfinite(v)
        for v in values
    ):
        raise ValueError("Non-finite input")

    low = min(values)
    high = max(values)

    if high == low:
        result = [0.5] * len(values)
    else:
        result = [
            (v - low) / (high - low)
            for v in values
        ]

    if reverse:
        result = [
            1.0 - v
            for v in result
        ]

    return result


def validate_boats(boats):
    if len(boats) not in (5, 6):
        raise ValueError(
            "Expected 5 or 6 boats"
        )

    numbers = [
        boat.number
        for boat in boats
    ]

    courses = [
        boat.course
        for boat in boats
    ]

    if len(set(numbers)) != len(boats):
        raise ValueError(
            "Duplicate boat number"
        )

    if len(set(courses)) != len(boats):
        raise ValueError(
            "Duplicate course"
        )

    if any(
        not 1 <= number <= 6
        for number in numbers
    ):
        raise ValueError(
            "Invalid boat number"
        )

    if any(
        not 1 <= course <= 6
        for course in courses
    ):
        raise ValueError(
            "Invalid course"
        )


def calculate_strengths(boats):
    validate_boats(boats)

    racer = normalize(
        [
            boat.racer_win_rate
            for boat in boats
        ]
    )

    motor = normalize(
        [
            boat.motor_2rate
            for boat in boats
        ]
    )

    exhibition = normalize(
        [
            boat.exhibition_time
            for boat in boats
        ],
        reverse=True,
    )

    start = normalize(
        [
            boat.average_st
            for boat in boats
        ],
        reverse=True,
    )

    course = normalize(
        [
            boat.course
            for boat in boats
        ],
        reverse=True,
    )

    strengths = {}

    for index, boat in enumerate(boats):
        score = (
            WEIGHTS["racer"]
            * racer[index]
            + WEIGHTS["motor"]
            * motor[index]
            + WEIGHTS["exhibition"]
            * exhibition[index]
            + WEIGHTS["start"]
            * start[index]
            + WEIGHTS["course"]
            * course[index]
        )

        strengths[boat.number] = exp(
            score
        )

    return strengths


def predict_probabilities(
    boats,
    bet_type="3T",
):
    if bet_type not in ("2T", "3T"):
        raise ValueError(
            "Invalid bet type"
        )

    strengths = calculate_strengths(
        boats
    )

    count = (
        2
        if bet_type == "2T"
        else 3
    )

    probabilities = {}

    for outcome in permutations(
        strengths.keys(),
        count,
    ):
        remaining = sum(
            strengths.values()
        )

        probability = 1.0

        for boat_number in outcome:
            strength = strengths[
                boat_number
            ]

            if remaining <= 0:
                raise ValueError(
                    "Invalid remaining strength"
                )

            probability *= (
                strength / remaining
            )

            remaining -= strength

        selection = "-".join(
            map(str, outcome)
        )

        probabilities[
            selection
        ] = probability

    total = sum(
        probabilities.values()
    )

    if (
        total <= 0
        or not isfinite(total)
    ):
        raise ValueError(
            "Invalid probability total"
        )

    normalized = {
        selection:
            probability / total
        for (
            selection,
            probability,
        ) in probabilities.items()
    }

    expected_count = (
        len(boats)
        * (len(boats) - 1)
        if bet_type == "2T"
        else
        len(boats)
        * (len(boats) - 1)
        * (len(boats) - 2)
    )

    if (
        len(normalized)
        != expected_count
    ):
        raise ValueError(
            "Incomplete probabilities"
        )

    return normalized


def evaluate_race(
    boats,
    odds_map,
    bet_type="3T",
    verified=False,
):
    from ev_engine import evaluate_ev

    probabilities = (
        predict_probabilities(
            boats,
            bet_type,
        )
    )

    results = []

    for (
        selection,
        odds,
    ) in odds_map.items():

        probability = (
            probabilities.get(
                selection
            )
        )

        if probability is None:
            continue

        result = evaluate_ev(
            selection=selection,
            odds=odds,
            probability=probability,
            verified=verified,
            bet_type=bet_type,
        )

        results.append(result)

    results.sort(
        key=lambda item: (
            item.decision
            != "CANDIDATE",
            -(
                item.ev
                if item.ev is not None
                else -999
            ),
            -(
                item.probability
                or 0
            ),
        )
    )

    return results


if __name__ == "__main__":
    print(
        "PROBABILITY_MODEL_READY",
        "UNVERIFIED",
    )
