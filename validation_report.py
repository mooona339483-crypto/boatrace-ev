
import sqlite3
from pathlib import Path

from backtest_engine import DEFAULT_DB


BET_TYPES = ("2T", "3T")


def empty_report():
    return {
        "status": "UNVERIFIED",
        "races": 0,
        "bets": 0,
        "hits": 0,
        "stake": 0,
        "payout": 0,
        "profit": None,
        "hit_rate": None,
        "roi": None,
        "pending_races": 0,
        "pending_bets": 0,
        "unverified_bets": 0,
    }


def validation_report(db_path=DEFAULT_DB):
    result = {
        bet_type: empty_report()
        for bet_type in BET_TYPES
    }

    if not Path(db_path).is_file():
        return result

    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row

        tables = {
            row["name"]
            for row in con.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table'"
            )
        }

        if not {"predictions", "results"}.issubset(tables):
            return result

        rows = con.execute("""
            SELECT
                p.race_id,
                p.bet_type,
                p.selection,
                p.probability,
                p.odds,
                p.stake,
                p.verified,
                r.winning_2t,
                r.winning_3t,
                r.payout_2t,
                r.payout_3t
            FROM predictions p
            LEFT JOIN results r
                ON p.race_id = r.race_id
            WHERE p.bet_type IN ('2T', '3T')
            ORDER BY p.race_id, p.bet_type
        """).fetchall()

    for bet_type in BET_TYPES:
        report = result[bet_type]

        matched = [
            row
            for row in rows
            if row["bet_type"] == bet_type
        ]

        verified_races = set()
        pending_races = set()

        for row in matched:
            if row["verified"] != 1:
                report["unverified_bets"] += 1
                continue

            if row["winning_2t"] is None:
                if bet_type == "2T":
                    pending_races.add(row["race_id"])
                    report["pending_bets"] += 1
                    continue

            if row["winning_3t"] is None:
                if bet_type == "3T":
                    pending_races.add(row["race_id"])
                    report["pending_bets"] += 1
                    continue

            verified_races.add(row["race_id"])

            report["bets"] += 1
            report["stake"] += row["stake"]

            if bet_type == "2T":
                winner = row["winning_2t"]
                dividend = row["payout_2t"]
            else:
                winner = row["winning_3t"]
                dividend = row["payout_3t"]

            if row["selection"] == winner:
                report["hits"] += 1
                report["payout"] += (
                    row["stake"] / 100.0
                ) * dividend

        report["races"] = len(verified_races)
        report["pending_races"] = len(pending_races)

        if report["pending_bets"] > 0:
            report["status"] = "PARTIAL_RESULTS"
        elif report["bets"] > 0:
            report["status"] = "VERIFIED_RECORDS"

        if report["bets"] > 0 and report["stake"] > 0:
            report["profit"] = round(
                report["payout"] - report["stake"],
                2,
            )
            report["hit_rate"] = (
                report["hits"] / report["bets"]
            )
            report["roi"] = (
                report["payout"] / report["stake"]
            )
            report["payout"] = round(
                report["payout"], 2
            )

    return result


if __name__ == "__main__":
    report = validation_report()

    for bet_type, values in report.items():
        print(
            "VALIDATION_REPORT",
            bet_type,
            values,
        )
