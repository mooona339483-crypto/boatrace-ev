
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DB = "backtest.sqlite3"


def connect(db_path=DEFAULT_DB):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(db_path=DEFAULT_DB):
    with connect(db_path) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id TEXT NOT NULL,
            bet_type TEXT NOT NULL,
            selection TEXT NOT NULL,
            probability REAL NOT NULL,
            odds REAL NOT NULL,
            stake INTEGER NOT NULL,
            deadline TEXT NOT NULL,
            predicted_at TEXT NOT NULL,
            source TEXT NOT NULL,
            verified INTEGER NOT NULL,
            UNIQUE(race_id, bet_type, selection)
        );

        CREATE TABLE IF NOT EXISTS results (
            race_id TEXT PRIMARY KEY,
            winning_2t TEXT NOT NULL,
            winning_3t TEXT NOT NULL,
            payout_2t REAL NOT NULL,
            payout_3t REAL NOT NULL
        );
        """)


def parse_time(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("Timezone required")
    return dt


def record_prediction(
    race_id,
    bet_type,
    selection,
    probability,
    odds,
    stake,
    deadline,
    predicted_at,
    source,
    verified,
    db_path=DEFAULT_DB,
):
    if bet_type not in ("2T", "3T"):
        raise ValueError("Invalid bet type")

    if not isinstance(verified, bool) or not verified:
        raise ValueError("Verified model required")

    if not source:
        raise ValueError("Prediction source required")

    if (
        not 0 < probability <= 1
        or not 1 < odds < float("inf")
    ):
        raise ValueError("Invalid probability or odds")

    if not isinstance(stake, int) or stake <= 0:
        raise ValueError("Invalid stake")

    predicted = parse_time(predicted_at)
    closing = parse_time(deadline)

    if predicted >= closing:
        raise ValueError("Prediction after deadline")

    if predicted > datetime.now(timezone.utc):
        raise ValueError("Future prediction prohibited")

    digits = selection.split("-")
    expected = 2 if bet_type == "2T" else 3

    if (
        len(digits) != expected
        or len(set(digits)) != expected
        or any(d not in "123456" for d in digits)
    ):
        raise ValueError("Invalid selection")

    with connect(db_path) as con:
        con.execute("""
            INSERT INTO predictions (
                race_id, bet_type, selection,
                probability, odds, stake,
                deadline, predicted_at,
                source, verified
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            race_id, bet_type, selection,
            probability, odds, stake,
            deadline, predicted_at, source
        ))


def record_result(
    race_id,
    winning_2t,
    winning_3t,
    payout_2t,
    payout_3t,
    db_path=DEFAULT_DB,
):
    if payout_2t < 0 or payout_3t < 0:
        raise ValueError("Invalid payout")

    with connect(db_path) as con:
        con.execute("""
            INSERT INTO results (
                race_id, winning_2t, winning_3t,
                payout_2t, payout_3t
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            race_id, winning_2t, winning_3t,
            payout_2t, payout_3t
        ))


def report(db_path=DEFAULT_DB):
    with connect(db_path) as con:
        rows = con.execute("""
            SELECT
                p.bet_type,
                p.race_id,
                p.selection,
                p.probability,
                p.odds,
                p.stake,
                r.winning_2t,
                r.winning_3t,
                r.payout_2t,
                r.payout_3t
            FROM predictions p
            JOIN results r ON p.race_id = r.race_id
            WHERE p.verified = 1
        """).fetchall()

    summary = {}

    for bet_type in ("2T", "3T"):
        selected = [
            row for row in rows
            if row["bet_type"] == bet_type
        ]

        total_stake = sum(row["stake"] for row in selected)
        total_payout = 0
        hits = 0

        for row in selected:
            if bet_type == "2T":
                winner = row["winning_2t"]
                dividend = row["payout_2t"]
            else:
                winner = row["winning_3t"]
                dividend = row["payout_3t"]

            if row["selection"] == winner:
                hits += 1
                total_payout += (
                    row["stake"] / 100.0
                ) * dividend

        total_bets = len(selected)

        summary[bet_type] = {
            "bets": total_bets,
            "hits": hits,
            "stake": total_stake,
            "payout": round(total_payout),
            "profit": round(total_payout - total_stake),
            "hit_rate": (
                hits / total_bets
                if total_bets else None
            ),
            "roi": (
                total_payout / total_stake
                if total_stake else None
            ),
            "status": (
                "VERIFIED_RECORDS"
                if total_bets else "UNTESTED"
            ),
        }

    return summary


if __name__ == "__main__":
    print(
        "BACKTEST_ENGINE_READY",
        "NO_PREDICTIONS_EXECUTED",
    )
