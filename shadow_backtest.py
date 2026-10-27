import json
import os
import sqlite3


DB = os.environ.get(
    "DB_PATH",
    "/data/boatrace_ev.sqlite3",
)

MODEL_VERSION = "heuristic-v1"

STAKE_PER_SELECTION = 100

MAX_SELECTIONS = {
    "2T": 5,
    "3T": 8,
}

EV_THRESHOLDS = (
    0.00,
    0.05,
    0.10,
    0.20,
    0.30,
    0.50,
    1.00,
)

CHECKPOINTS = (
    2,
    1,
)


def connect():
    con = sqlite3.connect(
        DB,
        timeout=30,
    )

    con.row_factory = sqlite3.Row

    return con


def load_records():
    with connect() as con:
        rows = con.execute(
            """
            SELECT
                s.id,
                s.race_id,
                s.bet_type,
                s.checkpoint_minutes,
                s.actual_minutes,
                s.model_version,
                s.selections_json,

                r.winning_2t,
                r.winning_3t,
                r.payout_2t,
                r.payout_3t

            FROM shadow_prediction_records AS s

            INNER JOIN race_results AS r
                ON r.race_id = s.race_id

            WHERE s.status='SHADOW_RECORDED'
              AND s.model_version=?

            ORDER BY
                s.race_id,
                s.checkpoint_minutes,
                s.bet_type
            """,
            (
                MODEL_VERSION,
            ),
        ).fetchall()

    return rows


def winner_and_payout(
    row,
):
    if row["bet_type"] == "2T":
        return (
            row["winning_2t"],
            row["payout_2t"],
        )

    if row["bet_type"] == "3T":
        return (
            row["winning_3t"],
            row["payout_3t"],
        )

    return (
        None,
        None,
    )


def select_candidates(
    selections,
    bet_type,
    min_ev,
):
    candidates = [
        item
        for item in selections
        if (
            isinstance(
                item.get("ev"),
                (int, float),
            )
            and item["ev"] >= min_ev
        )
    ]

    candidates.sort(
        key=lambda item: (
            -item["ev"],
            -item["probability"],
            item["selection"],
        )
    )

    return candidates[
        :MAX_SELECTIONS[
            bet_type
        ]
    ]


def evaluate_group(
    rows,
    checkpoint,
    bet_type,
    min_ev,
):
    available_races = 0
    races_with_bets = 0

    total_selections = 0
    total_stake = 0
    total_payout = 0

    hit_races = 0

    total_probability = 0.0
    total_ev = 0.0

    for row in rows:

        if (
            row["checkpoint_minutes"]
            != checkpoint
        ):
            continue

        if row["bet_type"] != bet_type:
            continue

        winner, payout = (
            winner_and_payout(
                row
            )
        )

        if (
            winner is None
            or payout is None
        ):
            continue

        available_races += 1

        try:
            selections = json.loads(
                row["selections_json"]
            )
        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            continue

        selected = (
            select_candidates(
                selections,
                bet_type,
                min_ev,
            )
        )

        if not selected:
            continue

        races_with_bets += 1

        race_hit = False

        for item in selected:

            total_selections += 1

            total_stake += (
                STAKE_PER_SELECTION
            )

            total_probability += (
                item["probability"]
            )

            total_ev += (
                item["ev"]
            )

            if (
                item["selection"]
                == winner
            ):
                race_hit = True

                total_payout += int(
                    round(
                        STAKE_PER_SELECTION
                        / 100
                        * payout
                    )
                )

        if race_hit:
            hit_races += 1

    profit = (
        total_payout
        - total_stake
    )

    roi = (
        total_payout
        / total_stake
        if total_stake
        else None
    )

    hit_rate = (
        hit_races
        / races_with_bets
        if races_with_bets
        else None
    )

    coverage = (
        races_with_bets
        / available_races
        if available_races
        else None
    )

    average_probability = (
        total_probability
        / total_selections
        if total_selections
        else None
    )

    average_ev = (
        total_ev
        / total_selections
        if total_selections
        else None
    )

    return {
        "checkpoint":
            checkpoint,

        "bet_type":
            bet_type,

        "min_ev":
            min_ev,

        "available_races":
            available_races,

        "races_with_bets":
            races_with_bets,

        "selections":
            total_selections,

        "hit_races":
            hit_races,

        "stake":
            total_stake,

        "payout":
            total_payout,

        "profit":
            profit,

        "roi":
            roi,

        "hit_rate":
            hit_rate,

        "coverage":
            coverage,

        "average_probability":
            average_probability,

        "average_ev":
            average_ev,
    }


def format_percent(
    value,
):
    if value is None:
        return "-"

    return (
        f"{value * 100:.1f}%"
    )


def run():
    rows = load_records()

    race_ids = {
        row["race_id"]
        for row in rows
    }

    print(
        "SHADOW_BACKTEST_START",
        "records=",
        len(rows),
        "races=",
        len(race_ids),
        "model=",
        MODEL_VERSION,
        flush=True,
    )

    if not rows:
        print(
            "SHADOW_BACKTEST_NO_DATA",
            flush=True,
        )
        return

    results = []

    for checkpoint in CHECKPOINTS:

        for bet_type in (
            "2T",
            "3T",
        ):

            for min_ev in EV_THRESHOLDS:

                result = evaluate_group(
                    rows,
                    checkpoint,
                    bet_type,
                    min_ev,
                )

                results.append(
                    result
                )

                print(
                    "BACKTEST",
                    "checkpoint=",
                    checkpoint,
                    "bet=",
                    bet_type,
                    "minEV=",
                    f"{min_ev:.2f}",
                    "available=",
                    result[
                        "available_races"
                    ],
                    "bet_races=",
                    result[
                        "races_with_bets"
                    ],
                    "selections=",
                    result[
                        "selections"
                    ],
                    "hits=",
                    result[
                        "hit_races"
                    ],
                    "stake=",
                    result[
                        "stake"
                    ],
                    "payout=",
                    result[
                        "payout"
                    ],
                    "profit=",
                    result[
                        "profit"
                    ],
                    "ROI=",
                    format_percent(
                        result["roi"]
                    ),
                    "hit_rate=",
                    format_percent(
                        result[
                            "hit_rate"
                        ]
                    ),
                    "coverage=",
                    format_percent(
                        result[
                            "coverage"
                        ]
                    ),
                    flush=True,
                )

    ranked = [
        result
        for result in results
        if (
            result["roi"]
            is not None
            and result[
                "races_with_bets"
            ] > 0
        )
    ]

    ranked.sort(
        key=lambda item: (
            -item["roi"],
            -item[
                "races_with_bets"
            ],
        )
    )

    print(
        "BACKTEST_TOP",
        flush=True,
    )

    for result in ranked[:10]:

        print(
            "TOP",
            "checkpoint=",
            result["checkpoint"],
            "bet=",
            result["bet_type"],
            "minEV=",
            f"{result['min_ev']:.2f}",
            "races=",
            result[
                "races_with_bets"
            ],
            "ROI=",
            format_percent(
                result["roi"]
            ),
            "profit=",
            result["profit"],
            flush=True,
        )

    if len(race_ids) < 30:
        print(
            "BACKTEST_WARNING",
            "sample_size_too_small",
            "races=",
            len(race_ids),
            "need_at_least=30",
            flush=True,
        )

    print(
        "SHADOW_BACKTEST_DONE",
        "races=",
        len(race_ids),
        flush=True,
    )


if __name__ == "__main__":
    run()
