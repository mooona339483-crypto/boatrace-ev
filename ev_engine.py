from dataclasses import dataclass
from math import isfinite


@dataclass
class EVResult:
    selection: str
    probability: float | None
    odds: float
    ev: float | None
    decision: str
    reason: str


MIN_EV = {
    "2T": 0.05,
    "3T": 0.05,
}

MIN_PROBABILITY = {
    "2T": 0.12,
    "3T": 0.08,
}


def evaluate_ev(
    selection,
    odds,
    probability=None,
    verified=False,
    bet_type="3T",
):
    if bet_type not in ("2T", "3T"):
        raise ValueError("Invalid bet type")

    if (
        not isinstance(odds, (int, float))
        or isinstance(odds, bool)
        or not isfinite(odds)
        or odds <= 1
    ):
        raise ValueError("Invalid odds")

    if not verified or probability is None:
        return EVResult(
            selection=selection,
            probability=None,
            odds=odds,
            ev=None,
            decision="SKIP",
            reason="Probability not verified",
        )

    if (
        not isinstance(probability, (int, float))
        or isinstance(probability, bool)
        or not isfinite(probability)
        or probability <= 0
        or probability > 1
    ):
        raise ValueError("Invalid probability")

    ev = probability * odds - 1

    if probability < MIN_PROBABILITY[bet_type]:
        decision = "SKIP"
        reason = "Low hit probability"

    elif ev < MIN_EV[bet_type]:
        decision = "SKIP"
        reason = "Insufficient expected value"

    else:
        decision = "CANDIDATE"
        reason = "Passed EV and probability filters"

    return EVResult(
        selection=selection,
        probability=probability,
        odds=odds,
        ev=round(ev, 4),
        decision=decision,
        reason=reason,
    )


def evaluate_many(
    bet_type,
    odds_map,
    probability_map,
    verified=False,
):
    results = []

    for selection, odds in odds_map.items():
        probability = probability_map.get(selection)

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
        key=lambda x: (
            x.decision != "CANDIDATE",
            -(x.ev if x.ev is not None else -999),
            -(x.probability or 0),
        )
    )

    return results


if __name__ == "__main__":
    test = evaluate_ev(
        selection="1-2-3",
        odds=15.0,
        probability=0.10,
        verified=True,
        bet_type="3T",
    )

    print(test)
