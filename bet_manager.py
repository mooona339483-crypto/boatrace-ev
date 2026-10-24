
from dataclasses import dataclass
from math import isfinite


BUDGET_PER_TYPE = 10000

MIN_EV = 0.05

MIN_PROBABILITY = {
    "2T": 0.12,
    "3T": 0.08,
}


@dataclass(frozen=True)
class BetCandidate:
    selection: str
    probability: float
    odds: float
    verified: bool


@dataclass(frozen=True)
class BetDecision:
    bet_type: str
    selection: str
    probability: float
    odds: float
    ev: float
    stake: int
    decision: str
    reason: str


def select_bets(
    bet_type,
    candidates,
    race_category="mixed",
    budget=BUDGET_PER_TYPE,
):
    if bet_type not in ("2T", "3T"):
        raise ValueError("Invalid bet type")

    if race_category not in ("male", "mixed", "female_only"):
        raise ValueError("Unknown race category")

    if not isinstance(budget, int) or isinstance(budget, bool):
        raise ValueError("Invalid budget")

    if budget < 0 or budget > BUDGET_PER_TYPE:
        raise ValueError("Budget limit exceeded")

    if race_category == "female_only":
        return []

    if budget < 100:
        return []

    valid = []
    seen = set()

    for candidate in candidates:
        selection = candidate.selection

        if selection in seen:
            raise ValueError("Duplicate selection")

        seen.add(selection)

        parts = selection.split("-")
        required = 2 if bet_type == "2T" else 3

        if (
            len(parts) != required
            or len(set(parts)) != required
            or any(p not in "123456" for p in parts)
        ):
            raise ValueError("Invalid selection")

        if not candidate.verified:
            continue

        p = candidate.probability
        odds = candidate.odds

        if (
            not isinstance(p, (int, float))
            or isinstance(p, bool)
            or not isfinite(p)
            or not 0 < p <= 1
            or not isinstance(odds, (int, float))
            or isinstance(odds, bool)
            or not isfinite(odds)
            or odds <= 1
        ):
            raise ValueError("Invalid probability or odds")

        ev = p * odds - 1

        if p < MIN_PROBABILITY[bet_type]:
            continue

        if ev < MIN_EV:
            continue

        valid.append((candidate, ev))

    if not valid:
        return []

    valid.sort(
        key=lambda x: (-x[1], -x[0].probability)
    )

    selected = []

    # 1点100円単位で均等配分する初期方式
    units = budget // 100
    count = min(len(valid), units)

    if count == 0:
        return []

    units_per_bet = units // count
    remainder = units % count

    for i, (candidate, ev) in enumerate(valid[:count]):
        stake = 100 * (
            units_per_bet + (1 if i < remainder else 0)
        )

        selected.append(
            BetDecision(
                bet_type=bet_type,
                selection=candidate.selection,
                probability=candidate.probability,
                odds=candidate.odds,
                ev=round(ev, 4),
                stake=stake,
                decision="VIRTUAL_CANDIDATE",
                reason="Passed preliminary filters",
            )
        )

    return selected


def summarize_bets(decisions):
    totals = {"2T": 0, "3T": 0}

    for decision in decisions:
        if decision.bet_type not in totals:
            raise ValueError("Invalid bet type")

        if decision.stake < 0 or decision.stake % 100:
            raise ValueError("Invalid stake")

        totals[decision.bet_type] += decision.stake

    for total in totals.values():
        if total > BUDGET_PER_TYPE:
            raise ValueError("Budget exceeded")

    return totals


if __name__ == "__main__":
    result = select_bets(
        bet_type="3T",
        candidates=[
            BetCandidate(
                selection="1-2-3",
                probability=0.10,
                odds=15.0,
                verified=False,
            )
        ],
    )

    print(
        "BET_MANAGER_READY",
        "SKIP" if not result else "VIRTUAL_ONLY",
    )
