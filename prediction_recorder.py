import json
import math
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")

DB = os.environ.get(
    "DB_PATH",
    "/data/boatrace_ev.sqlite3",
)

BUDGET_PER_TYPE = 10000


def now_jst():
    return datetime.now(JST)


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("Invalid time")

    dt = datetime.fromisoformat(value)

    if dt.tzinfo is None:
        raise ValueError(
            "Timezone required"
        )

    return dt.astimezone(JST)


def connect():
    con = sqlite3.connect(
        DB,
        timeout=30,
    )

    con.row_factory = sqlite3.Row

    return con


def init_db():
    with connect() as con:
        con.execute(
            """
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
                verified INTEGER NOT NULL,
                status TEXT NOT NULL,
                UNIQUE (
                    race_id,
                    bet_type,
                    model_version
                )
            )
            """
        )


def validate_selection(
    selection,
    bet_type,
):
    if not isinstance(
        selection,
        str,
    ):
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


def normalize_selections(
    selections,
    bet_type,
):
    if (
        not isinstance(
            selections,
            list,
        )
        or not selections
    ):
        raise ValueError(
            "No selections"
        )

    total_stake = 0
    seen = set()
    normalized = []

    for item in selections:

        if not isinstance(
            item,
            dict,
        ):
            raise ValueError(
                "Invalid selection item"
            )

        selection = item.get(
            "selection"
        )

        probability = item.get(
            "probability"
        )

        odds = item.get(
            "odds"
        )

        stake = item.get(
            "stake"
        )

        verified = item.get(
            "verified"
        )

        validate_selection(
            selection,
            bet_type,
        )

        if selection in seen:
            raise ValueError(
                "Duplicate selection"
            )

        seen.add(selection)

        if verified is not True:
            raise ValueError(
                "Unverified prediction"
            )

        if (
            not isinstance(
                probability,
                (int, float),
            )
            or isinstance(
                probability,
                bool,
            )
            or not math.isfinite(
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
            or not math.isfinite(
                odds
            )
            or odds <= 1
        ):
            raise ValueError(
                "Invalid odds"
            )

        if (
            not isinstance(
                stake,
                int,
            )
            or isinstance(
                stake,
                bool,
            )
            or stake <= 0
            or stake % 100 != 0
        ):
            raise ValueError(
                "Invalid stake"
            )

        total_stake += stake

        if (
            total_stake
            > BUDGET_PER_TYPE
        ):
            raise ValueError(
                "Budget exceeded"
            )

        ev = (
            probability
            * odds
            - 1
        )

        normalized.append(
            {
                "selection":
                    selection,
                "probability":
                    round(
                        probability,
                        8,
                    ),
                "odds":
                    odds,
                "stake":
                    stake,
                "ev":
                    round(
                        ev,
                        6,
                    ),
                "verified":
                    True,
            }
        )

    return (
        normalized,
        total_stake,
    )


def record_prediction(
    race_id,
    bet_type,
    race_category,
    deadline,
    model_version,
    selections,
    *,
    verified,
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
    ):
        raise ValueError(
            "Race excluded"
        )

    if verified is not True:
        raise ValueError(
            "Model not verified"
        )

    if not race_id:
        raise ValueError(
            "Missing race id"
        )

    if not model_version:
        raise ValueError(
            "Missing model version"
        )

    closing = parse_time(
        deadline
    )

    recorded_at = now_jst()

    if recorded_at >= closing:
        raise ValueError(
            "Deadline already passed"
        )

    (
        normalized,
        total_stake,
    ) = normalize_selections(
        selections,
        bet_type,
    )

    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )

    init_db()

    with connect() as con:
        con.execute(
            """
            INSERT INTO prediction_records (
                race_id,
                bet_type,
                race_category,
                deadline,
                recorded_at,
                model_version,
                selections_json,
                total_stake,
                verified,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                race_id,
                bet_type,
                race_category,
                closing.isoformat(),
                recorded_at.isoformat(),
                model_version,
                payload,
                total_stake,
                "VIRTUAL_RECORDED",
            ),
        )

    return {
        "race_id":
            race_id,
        "bet_type":
            bet_type,
        "total_stake":
            total_stake,
        "status":
            "VIRTUAL_RECORDED",
        "recorded_at":
            recorded_at.isoformat(),
    }


def get_records():
    init_db()

    with connect() as con:
        rows = con.execute(
            """
            SELECT
                *
            FROM prediction_records
            ORDER BY id
            """
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


if __name__ == "__main__":
    print(
        "PREDICTION_RECORDER_READY",
        "NO_VIRTUAL_BETS_PLACED",
    )
