
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


def evaluate_ev(
    selection,
    odds,
    probability=None,
    verified=False,
    min_ev=0.05,
    min_probability=0.08,
):
    if not isinstance(odds, (int, float)):
        raise ValueError("Invalid odds")

    if not isfinite(odds) or odds <= 1:
        raise ValueError("Invalid odds")

    if not verified or probability is None:
        return EVResult(
            selection, None, odds, None,
            "SKIP", "Probability not verified"
        )

    if (
        not isinstance(probability, (int, float))
        or not isfinite(probability)
        or not 0 <= probability <= 1
    ):
        raise ValueError("Invalid probability")

    ev = probability * odds - 1

    if probability < min_probability:
        decision = "SKIP"
        reason = "Low hit probability"
    elif ev < min_ev:
        decision = "SKIP"
        reason = "Insufficient expected value"
    else:
        decision = "CANDIDATE"
        reason = "Passed EV and probability filters"

    return EVResult(
        selection, probability, odds,
        round(ev, 4), decision, reason
    )


if __name__ == "__main__":
    result = evaluate_ev(
        selection="1-2-3",
        odds=15.0,
        probability=None,
        verified=False,
    )
    print(result)
