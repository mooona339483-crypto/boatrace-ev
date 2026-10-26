from dataclasses import dataclass
from math import isfinite


BUDGET_PER_TYPE = 10000

MIN_EV = {
    "2T": 0.05,
    "3T": 0.05,
}

MIN_PROBABILITY = {
    "2T": 0.12,
    "3T": 0.08,
}

MAX_SELECTIONS = {
    "2T": 5,
    "3T": 8,
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


def validate_selection(
    selection,
    bet_type,
):
    if not isinstance(selection, str):
        raise ValueError(
            "Invalid selection"
        )

    parts = selection.split("-")

    required = (
        2
        if bet_type == "2T"
        else 3
    )

    if (
        len(parts) != required
        or len(set(parts)) != required
        or any(
            part not in "123456"
            for part in parts
        )
    ):
        raise ValueError(
            "Invalid selection"
        )


def candidate_score(
    probability,
    ev,
):
    # EVだけでなく的中確率も重視
    return (
        ev * 0.60
        + probability * 0.40
    )


def select_bets(
    bet_type,
    candidates,
    race_category="mixed",
    budget=BUDGET_PER_TYPE,
):
    if bet_type not in (
        "2T",
        "3T",
    ):
        raise ValueError(
            "Invalid bet type"
        )

    if race_category not in (
        "male",
        "mixed",
        "female_only",
    ):
        raise ValueError(
            "Unknown race category"
        )

    if race_category == "female_only":
        return []

    if (
        not isinstance(budget, int)
        or isinstance(budget, bool)
        or budget < 0
        or budget > BUDGET_PER_TYPE
    ):
        raise ValueError(
            "Invalid budget"
        )

    if budget < 100:
        return []

    valid = []
    seen = set()

    for candidate in candidates:

        selection = candidate.selection

        if selection in seen:
            raise ValueError(
                "Duplicate selection"
            )

        seen.add(selection)

        validate_selection(
            selection,
            bet_type,
        )

        # 未検証モデルは買わない
        if candidate.verified is not True:
            continue

        probability = (
            candidate.probability
        )

        odds = candidate.odds

        if (
            not isinstance(
                probability,
                (int, float),
            )
            or isinstance(
                probability,
                bool,
            )
            or not isfinite(
                probability
            )
            or not 0 < probability <= 1
        ):
            raise ValueError(
                "Invalid probability"
            )

        if (
            not isinstance(
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
            raise ValueError(
                "Invalid odds"
            )

        ev = (
            probability
            * odds
            - 1
        )

        # 的中率が低ければ、
        # EVが高くても見送る
        if (
            probability
            < MIN_PROBABILITY[
                bet_type
            ]
        ):
            continue

        if (
            ev
            < MIN_EV[
                bet_type
            ]
        ):
            continue

        score = candidate_score(
            probability,
            ev,
        )

        valid.append(
            (
                candidate,
                ev,
                score,
            )
        )

    if not valid:
        return []

    # EVと的中確率の両方を考慮
    valid.sort(
        key=lambda item: (
            -item[2],
            -item[1],
            -item[0].probability,
        )
    )

    max_selections = (
        MAX_SELECTIONS[
            bet_type
        ]
    )

    selected = valid[
        :max_selections
    ]

    if not selected:
        return []

    # スコア比例で仮想資金配分
    positive_scores = [
        max(
            item[2],
            0.0001,
        )
        for item in selected
    ]

    score_total = sum(
        positive_scores
    )

    raw_units = []

    total_units = (
        budget // 100
    )

    for score in positive_scores:
        units = (
            total_units
            * score
            / score_total
        )

        raw_units.append(
            units
        )

    floor_units = [
        int(value)
        for value in raw_units
    ]

    used_units = sum(
        floor_units
    )

    remaining_units = (
        total_units
        - used_units
    )

    remainders = sorted(
        range(
            len(raw_units)
        ),
        key=lambda index:
            raw_units[index]
            - floor_units[index],
        reverse=True,
    )

    for index in remainders[
        :remaining_units
    ]:
        floor_units[
            index
        ] += 1

    decisions = []

    for index, (
        candidate,
        ev,
        score,
    ) in enumerate(selected):

        stake = (
            floor_units[index]
            * 100
        )

        if stake <= 0:
            continue

        decisions.append(
            BetDecision(
                bet_type=bet_type,
                selection=(
                    candidate.selection
                ),
                probability=round(
                    candidate.probability,
                    6,
                ),
                odds=candidate.odds,
                ev=round(
                    ev,
                    4,
                ),
                stake=stake,
                decision=(
                    "VIRTUAL_CANDIDATE"
                ),
                reason=(
                    "Passed EV and "
                    "hit probability filters"
                ),
            )
        )

    return decisions


def summarize_bets(
    decisions,
):
    totals = {
        "2T": 0,
        "3T": 0,
    }

    for decision in decisions:

        if (
            decision.bet_type
            not in totals
        ):
            raise ValueError(
                "Invalid bet type"
            )

        if (
            decision.stake <= 0
            or decision.stake % 100
        ):
            raise ValueError(
                "Invalid stake"
            )

        totals[
            decision.bet_type
        ] += decision.stake

    for total in totals.values():
        if (
            total
            > BUDGET_PER_TYPE
        ):
            raise ValueError(
                "Budget exceeded"
            )

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
            ),
        ],
    )

    print(
        "BET_MANAGER_READY",
        "SKIP"
        if not result
        else "VIRTUAL_ONLY",
    )
