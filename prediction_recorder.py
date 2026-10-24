
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DB = "prediction_records.sqlite3"
BUDGET_PER_TYPE = 10000


def utc_now():
    return datetime.now(timezone.utc)


def parse_time(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timezone required")
    return dt.astimezone(timezone.utc)


def connect(db_path=DEFAULT_DB):
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(db_path=DEFAULT_DB):
    with connect(db_path) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS prediction_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id TEXT NOT NULL,
                bet_type TEXT NOT NULL,
                race_category TEXT NOT NULL,
                deadline TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                model_version TEXT NOT NULL,
                selections_json TEXT NOT NULL,
                total_stake INTEGER NOT NULL,
                UNIQUE(race_id, bet_type)
            )
        """)


def validate_selection(selection, bet_type):
    if not isinstance(selection, str):
        raise ValueError("Invalid selection")

    parts = selection.split("-")
    required = 2 if bet_type == "2T" else 3

    if (
        len(parts) != required
        or len(set(parts)) != required
        or any(p not in "123456" for p in parts)
    ):
        raise ValueError("Invalid selection")


def record_prediction(
    race_id,
    bet_type,
    race_category,
    deadline,
    model_version,
    selections,
    db_path=DEFAULT_DB,
    recorded_at=None,
):
    if bet_type not in ("2T", "3T"):
        raise ValueError("Invalid bet type")

    if race_category not in ("male", "mixed"):
        raise ValueError("Race excluded")

    if not race_id or not model_version:
        raise ValueError("Missing identity or model")

    closing = parse_time(deadline)
    now = utc_now()

    # recorded_at is metadata, not an authority
    if recorded_at is not None:
        supplied = parse_time(recorded_at)
        if abs((now - supplied).total_seconds()) > 30:
            raise ValueError("Recorded time mismatch")

    if now >= closing:
        raise ValueError("Deadline already passed")

    if not isinstance(selections, list) or not selections:
        raise ValueError("No selections")

    total_stake = 0
    seen = set()
    normalized = []

    for item in selections:
        selection = item["selection"]
        probability = item["probability"]
        odds = item["odds"]
        stake = item["stake"]
        verified = item["verified"]

        validate_selection(selection, bet_type)

        if selection in seen:
            raise ValueError("Duplicate selection")
        seen.add(selection)

        if verified is not True:
            raise ValueError("Unverified prediction")

        if (
            not isinstance(probability, (int, float))
            or isinstance(probability, bool)
            or not math.isfinite(probability)
            or not 0 < probability <= 1
        ):
            raise ValueError("Invalid probability")

        if (
            not isinstance(odds, (int, float))
            or isinstance(odds, bool)
            or not math.isfinite(odds)
            or odds <= 1
        ):
            raise ValueError("Invalid odds")

        if (
            not isinstance(stake, int)
            or isinstance(stake, bool)
            or stake <= 0
            or stake % 100 != 0
        ):
            raise ValueError("Invalid stake")

        total_stake += stake

        if total_stake > BUDGET_PER_TYPE:
            raise ValueError("Budget exceeded")

        normalized.append({
            "selection": selection,
            "probability": probability,
            "odds": odds,
            "stake": stake,
            "ev": round(probability * odds - 1, 6),
        })

    # A local timestamp cannot prove an external
    # prediction or odds were available before cutoff.
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    with connect(db_path) as con:
        con.execute(
            """
            INSERT INTO prediction_records (
                race_id, bet_type, race_category,
                deadline, recorded_at, model_version,
                selections_json, total_stake
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                race_id,
                bet_type,
                race_category,
                closing.isoformat(),
                now.isoformat(),
                model_version,
                payload,
                total_stake,
            ),
        )

    return {
        "race_id": race_id,
        "bet_type": bet_type,
        "total_stake": total_stake,
        "status": "VIRTUAL_RECORDED",
    }


def get_records(db_path=DEFAULT_DB):
    with connect(db_path) as con:
        rows = con.execute("""
            SELECT *
            FROM prediction_records
            ORDER BY id
        """).fetchall()

    return [dict(row) for row in rows]


if __name__ == "__main__":
    print(
        "PREDICTION_RECORDER_READY",
        "NO_VIRTUAL_BETS_PLACED",
    )
