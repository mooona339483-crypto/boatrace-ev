from result_resolution import load_resolution_index, is_terminal, settle_selections
import json
import math
import os
import sqlite3

DB = os.environ.get("DB_PATH", "/data/boatrace_ev.sqlite3")
MODEL_VERSION = "heuristic-v1"

STAKE_PER_SELECTION = 100
MIN_PROBABILITY = {"2T": 0.12, "3T": 0.08}
MAX_SELECTIONS = {"2T": 5, "3T": 8}
EV_THRESHOLDS = (0.00, 0.05, 0.10, 0.20, 0.30, 0.50, 1.00)
DIAGNOSTIC_MIN_EV = 0.05
CHECKPOINTS = (2, 1)

REASON_PRIORITY = {
    "DATA_MISSING": 0,
    "OTHER": 1,
    "LOW_PROBABILITY": 2,
    "LOW_EV": 3,
    "CANDIDATE": 4,
}


def connect():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _attach_resolution(rows, resolutions):
    result = []
    for raw in rows:
        row = dict(raw)
        present = row["race_id"] in resolutions
        outcome = resolutions.get(row["race_id"])
        row["_resolution_present"] = present
        row["_resolution"] = outcome
        if "result_exists" in row:
            if present:
                row["result_exists"] = int(is_terminal(outcome))
                market = next((m for m in outcome.markets if m.bet_type == row.get("bet_type")), None) if outcome else None
                row["result_state"] = market.state if market else ("RESOLVED" if is_terminal(outcome) else "UNKNOWN")
            elif "bet_type" in row:
                winner, payout = winner_and_payout(row)
                row["result_exists"] = int(valid_selection(winner, row["bet_type"]) and valid_number(payout) and payout >= 0)
            else:
                row["result_exists"] = int(all(valid_selection(row.get("winning_"+bet.lower()), bet) and valid_number(row.get("payout_"+bet.lower())) and row["payout_"+bet.lower()] >= 0 for bet in ("2T", "3T")))
        result.append(row)
    return result


def load_records():
    with connect() as con:
        resolutions = load_resolution_index(con)
        rows = con.execute("""
            SELECT s.id, s.race_id, s.bet_type, s.checkpoint_minutes,
                   s.actual_minutes, s.model_version, s.selections_json,
                   r.winning_2t, r.winning_3t, r.payout_2t, r.payout_3t,
                   r.race_id AS legacy_result_exists
            FROM shadow_prediction_records s LEFT JOIN race_results r ON r.race_id=s.race_id
            WHERE s.status='SHADOW_RECORDED' AND s.model_version=?
            ORDER BY s.race_id, s.checkpoint_minutes, s.bet_type
        """, (MODEL_VERSION,)).fetchall()
        rows = [row for row in _attach_resolution(rows, resolutions)
                if row["legacy_result_exists"] is not None or row["_resolution_present"]]
    return list(unique_records(rows))


def load_diagnostic_records():
    with connect() as con:
        resolutions = load_resolution_index(con)
        rows = con.execute("""
            SELECT s.race_id, s.bet_type, s.checkpoint_minutes, s.selections_json,
                   r.winning_2t, r.winning_3t, r.payout_2t, r.payout_3t,
                   CASE WHEN r.race_id IS NOT NULL THEN 1 ELSE 0 END AS result_exists
            FROM shadow_prediction_records s LEFT JOIN race_results r ON r.race_id=s.race_id
            WHERE s.status='SHADOW_RECORDED' AND s.model_version=?
            ORDER BY s.race_id, s.checkpoint_minutes, s.bet_type
        """, (MODEL_VERSION,)).fetchall()
        return _attach_resolution(rows, resolutions)


def load_checkpoint_status():
    with connect() as con:
        resolutions = load_resolution_index(con)
        rows = con.execute("""
            SELECT o.race_id, o.checkpoint_minutes,
                   MAX(CASE WHEN o.bet_type='2T' THEN 1 ELSE 0 END) AS has_2t,
                   MAX(CASE WHEN o.bet_type='3T' THEN 1 ELSE 0 END) AS has_3t,
                   r.winning_2t, r.winning_3t, r.payout_2t, r.payout_3t,
                   CASE WHEN r.race_id IS NOT NULL THEN 1 ELSE 0 END AS result_exists
            FROM odds_checkpoints o LEFT JOIN race_results r ON r.race_id=o.race_id
            WHERE o.checkpoint_minutes IN (1,2)
            GROUP BY o.race_id, o.checkpoint_minutes
            ORDER BY o.race_id, o.checkpoint_minutes
        """).fetchall()
        return _attach_resolution(rows, resolutions)


def valid_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False

    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def valid_selection(selection, bet_type):
    if bet_type not in MIN_PROBABILITY or not isinstance(selection, str):
        return False

    parts = selection.split("-")
    required = 2 if bet_type == "2T" else 3

    return (
        len(parts) == required
        and len(set(parts)) == required
        and all(
            part in {"1", "2", "3", "4", "5", "6"}
            for part in parts
        )
    )


def valid_item(item, bet_type):
    if not isinstance(item, dict):
        return False

    probability = item.get("probability")
    odds = item.get("odds")

    return (
        valid_selection(
            item.get("selection"),
            bet_type,
        )
        and valid_number(probability)
        and 0 < probability <= 1
        and valid_number(odds)
        and odds > 1
        and valid_number(item.get("ev"))
    )


def unique_records(rows):
    seen = set()

    for row in rows:
        key = (
            row["race_id"],
            row["checkpoint_minutes"],
            row["bet_type"],
            row["model_version"],
        )

        if key in seen:
            continue

        seen.add(key)
        yield row


def empty_counts():
    return {
        "total": 0,
        "invalid": 0,
        "low_probability": 0,
        "low_ev": 0,
        "candidate": 0,
    }


def diagnose_selections(
    selections,
    bet_type,
    min_ev=DIAGNOSTIC_MIN_EV,
):
    counts = empty_counts()
    max_probability = None

    if (
        bet_type not in MIN_PROBABILITY
        or not isinstance(selections, list)
    ):
        return {
            "reason": "OTHER",
            "counts": counts,
            "max_probability": None,
        }

    min_probability = MIN_PROBABILITY[bet_type]

    for item in selections:
        counts["total"] += 1

        if not valid_item(item, bet_type):
            counts["invalid"] += 1
            continue

        probability = item["probability"]
        ev = item["ev"]

        if (
            max_probability is None
            or probability > max_probability
        ):
            max_probability = probability

        if probability < min_probability:
            counts["low_probability"] += 1

        elif ev < min_ev:
            counts["low_ev"] += 1

        else:
            counts["candidate"] += 1

    valid_count = (
        counts["total"]
        - counts["invalid"]
    )

    if valid_count <= 0:
        reason = "OTHER"

    elif counts["candidate"] > 0:
        reason = "CANDIDATE"

    elif counts["low_ev"] > 0:
        reason = "LOW_EV"

    else:
        reason = "LOW_PROBABILITY"

    return {
        "reason": reason,
        "counts": counts,
        "max_probability": max_probability,
    }


def slot_key(
    race_id,
    checkpoint,
    bet_type,
):
    return (
        str(race_id),
        int(checkpoint),
        str(bet_type),
    )


def build_diagnostics(
    diagnostic_rows,
    checkpoint_rows,
):
    slots = {}

    # 同じ race/checkpoint/bet は1回だけ集計
    for row in diagnostic_rows:
        key = slot_key(
            row["race_id"],
            row["checkpoint_minutes"],
            row["bet_type"],
        )

        if key in slots:
            continue

        try:
            selections = json.loads(
                row["selections_json"]
            )

        except (
            TypeError,
            ValueError,
            RecursionError,
        ):
            slots[key] = {
                "reason": "OTHER",
                "detail": "invalid_json",
                "counts": {
                    **empty_counts(),
                    "invalid": 1,
                },
                "max_probability": None,
                "result_exists": bool(
                    row["result_exists"]
                ),
            }

            continue

        info = diagnose_selections(
            selections,
            row["bet_type"],
        )

        info["detail"] = "shadow_record"
        info["result_state"] = dict(row).get("result_state", "LEGACY")
        info["result_exists"] = bool(
            row["result_exists"]
        )

        slots[key] = info

    seen_checkpoint = set()

    for row in checkpoint_rows:
        race_id = str(
            row["race_id"]
        )

        checkpoint = int(
            row["checkpoint_minutes"]
        )

        cp_key = (
            race_id,
            checkpoint,
        )

        if cp_key in seen_checkpoint:
            continue

        seen_checkpoint.add(
            cp_key
        )

        for bet_type in (
            "2T",
            "3T",
        ):
            key = slot_key(
                race_id,
                checkpoint,
                bet_type,
            )

            has_odds = bool(
                row[
                    "has_2t"
                    if bet_type == "2T"
                    else "has_3t"
                ]
            )

            if not has_odds:
                slots[key] = {
                    "reason":
                        "DATA_MISSING",

                    "detail":
                        "missing_odds_checkpoint",

                    "counts":
                        empty_counts(),

                    "max_probability":
                        None,

                    "result_exists":
                        bool(
                            row[
                                "result_exists"
                            ]
                        ),
                }

            elif key not in slots:
                slots[key] = {
                    "reason":
                        "DATA_MISSING",

                    "detail":
                        "missing_shadow_record",

                    "counts":
                        empty_counts(),

                    "max_probability":
                        None,

                    "result_exists":
                        bool(
                            row[
                                "result_exists"
                            ]
                        ),
                }

    race_reasons = {}
    pending_races = set()

    # race_id は1回だけ集計
    for (
        race_id,
        _checkpoint,
        _bet_type,
    ), info in slots.items():

        if not info[
            "result_exists"
        ]:
            pending_races.add(
                race_id
            )
            continue

        reason = info["reason"]

        current = race_reasons.get(
            race_id
        )

        if (
            current is None
            or REASON_PRIORITY[
                reason
            ]
            < REASON_PRIORITY[
                current
            ]
        ):
            race_reasons[
                race_id
            ] = reason

    for race_id in pending_races:
        race_reasons.pop(race_id, None)

    return {
        "slots":
            slots,

        "race_reasons":
            race_reasons,

        "pending_races":
            pending_races,
    }


def candidate_score(
    probability,
    ev,
):
    return (
        ev * 0.60
        + probability * 0.40
    )


def select_candidates(
    selections,
    bet_type,
    min_ev,
):
    if (
        bet_type not in MIN_PROBABILITY
        or not isinstance(
            selections,
            list,
        )
    ):
        return []

    valid = []

    min_probability = (
        MIN_PROBABILITY[
            bet_type
        ]
    )

    for item in selections:

        if not valid_item(
            item,
            bet_type,
        ):
            continue

        probability = (
            item["probability"]
        )

        ev = item["ev"]

        if (
            probability
            < min_probability
            or ev < min_ev
        ):
            continue

        valid.append(
            (
                item,
                candidate_score(
                    probability,
                    ev,
                ),
            )
        )

    valid.sort(
        key=lambda pair: (
            -pair[1],
            -pair[0]["ev"],
            -pair[0][
                "probability"
            ],
            pair[0][
                "selection"
            ],
        )
    )

    return [
        pair[0]
        for pair in valid[
            :MAX_SELECTIONS[
                bet_type
            ]
        ]
    ]


def winner_and_payout(
    row,
):
    if row["bet_type"] == "2T":
        return (
            row["winning_2t"],
            row["payout_2t"],
        )

    return (
        row["winning_3t"],
        row["payout_3t"],
    )


def evaluate_group(rows, checkpoint, bet_type, min_ev):
    available = bet_races = selections_count = hits = stake = payout_total = 0
    refund_stake = decision_races = void_races = pending_results = 0
    for raw in unique_records(rows):
        row = dict(raw)
        if row["checkpoint_minutes"] != checkpoint or row["bet_type"] != bet_type:
            continue
        outcome = row.get("_resolution")
        present = row.get("_resolution_present", False)
        if present:
            if not is_terminal(outcome):
                pending_results += 1
                continue
            market = next(m for m in outcome.markets if m.bet_type == bet_type)
            void_races += market.state == "VOID"
        else:
            winner, payout = winner_and_payout(row)
            if not valid_selection(winner, bet_type) or not valid_number(payout) or payout < 0:
                continue
        available += 1
        try:
            selections = json.loads(row["selections_json"])
        except (TypeError, ValueError, RecursionError):
            continue
        selected = select_candidates(selections, bet_type, min_ev)
        if not selected:
            continue
        if present:
            tickets = [{"selection": item["selection"], "stake": STAKE_PER_SELECTION} for item in selected]
            result = settle_selections(outcome, bet_type, tickets)
            if result is None:
                pending_results += 1
                continue
            row_payout = result["total_payout"]
            row_hits = result["hits"]
            refund_stake += result["refund_stake"]
            decision_races += result["has_decision"]
        else:
            row_hits = sum(item["selection"] == winner for item in selected)
            row_payout = row_hits * int(round(STAKE_PER_SELECTION / 100 * payout))
            decision_races += 1
        bet_races += 1
        selections_count += len(selected)
        stake += len(selected) * STAKE_PER_SELECTION
        payout_total += row_payout
        hits += row_hits > 0
    return {"checkpoint": checkpoint, "bet_type": bet_type, "min_ev": min_ev,
            "min_probability": MIN_PROBABILITY[bet_type], "available_races": available,
            "races_with_bets": bet_races, "selections": selections_count,
            "hit_races": hits, "stake": stake, "payout": payout_total,
            "profit": payout_total - stake, "roi": payout_total / stake if stake else None,
            "hit_rate": hits / decision_races if decision_races else None,
            "coverage": bet_races / available if available else None,
            "refund_stake": refund_stake, "decision_races": decision_races,
            "void_races": void_races, "pending_result_races": pending_results}


def format_percent(
    value,
):
    if value is None:
        return "N/A"

    return (
        f"{value * 100:.1f}%"
    )


def print_diagnostics(
    diagnostics,
):
    slots = diagnostics[
        "slots"
    ]

    print(
        "DIAG_START",
        f"minEV={format_percent(DIAGNOSTIC_MIN_EV)}",
        f"minProb2T={format_percent(MIN_PROBABILITY['2T'])}",
        f"minProb3T={format_percent(MIN_PROBABILITY['3T'])}",
        flush=True,
    )

    for checkpoint in CHECKPOINTS:

        for bet_type in (
            "2T",
            "3T",
        ):
            selected = [
                info
                for key, info
                in slots.items()
                if (
                    key[1]
                    == checkpoint
                    and key[2]
                    == bet_type
                    and info[
                        "result_exists"
                    ]
                )
            ]

            reasons = {
                reason: 0
                for reason
                in REASON_PRIORITY
            }

            selections = {
                "invalid": 0,
                "low_probability": 0,
                "low_ev": 0,
                "candidate": 0,
            }

            max_probability = None

            for info in selected:

                reasons[
                    info["reason"]
                ] += 1

                for name in selections:
                    selections[
                        name
                    ] += info[
                        "counts"
                    ][name]

                value = info[
                    "max_probability"
                ]

                if (
                    value is not None
                    and (
                        max_probability
                        is None
                        or value
                        > max_probability
                    )
                ):
                    max_probability = (
                        value
                    )

            print(
                "DIAG_SLOT_SUMMARY",
                f"checkpoint={checkpoint}",
                f"bet={bet_type}",
                f"slots={len(selected)}",
                f"void_slots={sum(info.get('result_state') == 'VOID' for info in selected)}",
                f"data_missing={reasons['DATA_MISSING']}",
                f"low_probability={reasons['LOW_PROBABILITY']}",
                f"low_ev={reasons['LOW_EV']}",
                f"other={reasons['OTHER']}",
                f"candidate={reasons['CANDIDATE']}",
                f"selection_low_probability={selections['low_probability']}",
                f"selection_low_ev={selections['low_ev']}",
                f"selection_invalid={selections['invalid']}",
                f"max_probability={format_percent(max_probability)}",
                flush=True,
            )

    reason_to_races = {
        reason: []
        for reason
        in REASON_PRIORITY
    }

    for (
        race_id,
        reason,
    ) in sorted(
        diagnostics[
            "race_reasons"
        ].items()
    ):
        reason_to_races[
            reason
        ].append(
            race_id
        )

    print(
        "DIAG_RACE_SUMMARY",
        f"unique_completed_races={len(diagnostics['race_reasons'])}",
        f"pending_races={len(diagnostics['pending_races'])}",
        f"data_missing={len(reason_to_races['DATA_MISSING'])}",
        f"low_probability={len(reason_to_races['LOW_PROBABILITY'])}",
        f"low_ev={len(reason_to_races['LOW_EV'])}",
        f"other={len(reason_to_races['OTHER'])}",
        f"candidate={len(reason_to_races['CANDIDATE'])}",
        flush=True,
    )

    for reason in (
        "DATA_MISSING",
        "LOW_PROBABILITY",
        "LOW_EV",
        "OTHER",
        "CANDIDATE",
    ):
        races = (
            reason_to_races[
                reason
            ]
        )

        if races:
            print(
                "DIAG_RACES",
                f"reason={reason}",
                f"count={len(races)}",
                "races="
                + ",".join(
                    races
                ),
                flush=True,
            )

    missing_details = {}

    for (
        race_id,
        _checkpoint,
        _bet_type,
    ), info in slots.items():

        if (
            info[
                "reason"
            ]
            == "DATA_MISSING"
            and info[
                "result_exists"
            ]
        ):
            missing_details.setdefault(
                info["detail"],
                set(),
            ).add(
                race_id
            )

    for (
        detail,
        races,
    ) in sorted(
        missing_details.items()
    ):
        print(
            "DIAG_DATA_MISSING",
            f"detail={detail}",
            f"count={len(races)}",
            "races="
            + ",".join(
                sorted(races)
            ),
            flush=True,
        )

    print(
        "DIAG_DONE",
        flush=True,
    )


def print_backtest(
    result,
):
    print(
        "BACKTEST",
        f"checkpoint={result['checkpoint']}",
        f"bet={result['bet_type']}",
        f"minProb={format_percent(result['min_probability'])}",
        f"minEV={format_percent(result['min_ev'])}",
        f"available={result['available_races']}",
        f"decision_races={result.get('decision_races', 0)}",
        f"void_races={result.get('void_races', 0)}",
        f"refund_stake={result.get('refund_stake', 0)}",
        f"pending_result_races={result.get('pending_result_races', 0)}",
        f"bet_races={result['races_with_bets']}",
        f"selections={result['selections']}",
        f"hits={result['hit_races']}",
        f"stake={result['stake']}",
        f"payout={result['payout']}",
        f"profit={result['profit']}",
        f"ROI={format_percent(result['roi'])}",
        f"hit_rate={format_percent(result['hit_rate'])}",
        f"coverage={format_percent(result['coverage'])}",
        flush=True,
    )


def run():
    rows = load_records()

    diagnostics = (
        build_diagnostics(
            load_diagnostic_records(),
            load_checkpoint_status(),
        )
    )

    print_diagnostics(
        diagnostics
    )

    race_ids = {
        row["race_id"] for row in rows
        if ((not row.get("_resolution_present", False)
             and valid_selection(winner_and_payout(row)[0], row["bet_type"])
             and valid_number(winner_and_payout(row)[1]))
            or (is_terminal(row.get("_resolution"))
                and any(m.bet_type == row["bet_type"] and m.state == "SETTLED" for m in row["_resolution"].markets)))
    }

    print(
        "SHADOW_BACKTEST_START",
        f"records={len(rows)}",
        f"races={len(race_ids)}",
        f"model={MODEL_VERSION}",
        "races_scope=decision_capable",
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

            for min_ev in (
                EV_THRESHOLDS
            ):
                result = (
                    evaluate_group(
                        rows,
                        checkpoint,
                        bet_type,
                        min_ev,
                    )
                )

                results.append(
                    result
                )

                print_backtest(
                    result
                )

    ranked = [
        result
        for result in results
        if (
            result[
                "roi"
            ]
            is not None
            and result[
                "races_with_bets"
            ] > 0
            and result["decision_races"] > 0
        )
    ]

    ranked.sort(
        key=lambda item: (
            -item[
                "roi"
            ],
            -item[
                "races_with_bets"
            ],
        )
    )

    print(
        "BACKTEST_TOP",
        flush=True,
    )

    for result in ranked[
        :10
    ]:
        print(
            "TOP",
            f"checkpoint={result['checkpoint']}",
            f"bet={result['bet_type']}",
            f"minProb={format_percent(result['min_probability'])}",
            f"minEV={format_percent(result['min_ev'])}",
            f"races={result['races_with_bets']}",
            f"ROI={format_percent(result['roi'])}",
            f"hit_rate={format_percent(result['hit_rate'])}",
            f"coverage={format_percent(result['coverage'])}",
            f"profit={result['profit']}",
            flush=True,
        )

    if len(race_ids) < 30:
        print(
            "BACKTEST_WARNING",
            "sample_size_too_small",
            f"races={len(race_ids)}",
            "need_at_least=30",
            flush=True,
        )

    print(
        "SHADOW_BACKTEST_DONE",
        f"races={len(race_ids)}",
        flush=True,
    )


if __name__ == "__main__":
    run()
