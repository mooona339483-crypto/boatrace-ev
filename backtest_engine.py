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
            CREATE TABLE IF NOT EXISTS race_results (
                race_id TEXT PRIMARY KEY,
                winning_2t TEXT,
                winning_3t TEXT,
                payout_2t REAL,
                payout_3t REAL,
                recorded_at TEXT NOT NULL
            )
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS settlement_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_id INTEGER NOT NULL,
                race_id TEXT NOT NULL,
                bet_type TEXT NOT NULL,
                total_stake INTEGER NOT NULL,
                total_payout INTEGER NOT NULL,
                profit INTEGER NOT NULL,
                hits INTEGER NOT NULL,
                settled_at TEXT NOT NULL,
                UNIQUE(prediction_id)
            )
            """
        )


def validate_selection(
    selection,
    bet_type,
):
    if selection is None:
        return

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


def validate_payout(
    payout,
):
    if payout is None:
        return

    if (
        not isinstance(
            payout,
            (int, float),
        )
        or isinstance(
            payout,
            bool,
        )
        or not math.isfinite(
            payout
        )
        or payout < 0
    ):
        raise ValueError(
            "Invalid payout"
        )


def record_result(
    race_id,
    winning_2t,
    winning_3t,
    payout_2t,
    payout_3t,
):
    if not race_id:
        raise ValueError(
            "Missing race id"
        )

    validate_selection(
        winning_2t,
        "2T",
    )

    validate_selection(
        winning_3t,
        "3T",
    )

    validate_payout(
        payout_2t,
    )

    validate_payout(
        payout_3t,
    )

    recorded_at = (
        datetime.now(JST)
        .isoformat()
    )

    init_db()

    with connect() as con:
        con.execute(
            """
            INSERT OR REPLACE INTO race_results (
                race_id,
                winning_2t,
                winning_3t,
                payout_2t,
                payout_3t,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                race_id,
                winning_2t,
                winning_3t,
                payout_2t,
                payout_3t,
                recorded_at,
            ),
        )


def settle_prediction(
    prediction_row,
    result_row,
):
    bet_type = (
        prediction_row[
            "bet_type"
        ]
    )

    selections = json.loads(
        prediction_row[
            "selections_json"
        ]
    )

    if bet_type == "2T":
        winner = (
            result_row[
                "winning_2t"
            ]
        )

        dividend = (
            result_row[
                "payout_2t"
            ]
        )

    elif bet_type == "3T":
        winner = (
            result_row[
                "winning_3t"
            ]
        )

        dividend = (
            result_row[
                "payout_3t"
            ]
        )

    else:
        raise ValueError(
            "Invalid bet type"
        )

    if (
        winner is None
        or dividend is None
    ):
        return None

    total_stake = 0
    total_payout = 0
    hits = 0

    for item in selections:

        selection = item[
            "selection"
        ]

        stake = item[
            "stake"
        ]

        if (
            not isinstance(
                stake,
                int,
            )
            or stake <= 0
            or stake % 100 != 0
        ):
            raise ValueError(
                "Invalid stake"
            )

        total_stake += stake

        if selection == winner:
            hits += 1

            payout = (
                stake
                / 100.0
                * dividend
            )

            total_payout += round(
                payout
            )

    profit = (
        total_payout
        - total_stake
    )

    return {
        "prediction_id":
            prediction_row[
                "id"
            ],
        "race_id":
            prediction_row[
                "race_id"
            ],
        "bet_type":
            bet_type,
        "total_stake":
            total_stake,
        "total_payout":
            total_payout,
        "profit":
            profit,
        "hits":
            hits,
    }


def settle_all():
    init_db()

    settled_at = (
        datetime.now(JST)
        .isoformat()
    )

    settled = 0
    skipped = 0

    with connect() as con:

        rows = con.execute(
            """
            SELECT
                p.*,
                r.winning_2t,
                r.winning_3t,
                r.payout_2t,
                r.payout_3t
            FROM prediction_records p
            JOIN race_results r
              ON p.race_id = r.race_id
            LEFT JOIN settlement_records s
              ON p.id = s.prediction_id
            WHERE p.verified=1
              AND s.id IS NULL
            ORDER BY p.id
            """
        ).fetchall()

        for row in rows:

            result = settle_prediction(
                row,
                row,
            )

            if result is None:
                skipped += 1
                continue

            con.execute(
                """
                INSERT INTO settlement_records (
                    prediction_id,
                    race_id,
                    bet_type,
                    total_stake,
                    total_payout,
                    profit,
                    hits,
                    settled_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result[
                        "prediction_id"
                    ],
                    result[
                        "race_id"
                    ],
                    result[
                        "bet_type"
                    ],
                    result[
                        "total_stake"
                    ],
                    result[
                        "total_payout"
                    ],
                    result[
                        "profit"
                    ],
                    result[
                        "hits"
                    ],
                    settled_at,
                ),
            )

            settled += 1

    return {
        "settled":
            settled,
        "skipped":
            skipped,
    }


def report():
    init_db()

    with connect() as con:
        rows = con.execute(
            """
            SELECT
                bet_type,
                COUNT(*) AS races,
                SUM(total_stake)
                    AS total_stake,
                SUM(total_payout)
                    AS total_payout,
                SUM(profit)
                    AS total_profit,
                SUM(
                    CASE
                        WHEN hits > 0
                        THEN 1
                        ELSE 0
                    END
                ) AS hit_races
            FROM settlement_records
            GROUP BY bet_type
            """
        ).fetchall()

    summary = {
        "2T": {
            "races": 0,
            "hit_races": 0,
            "stake": 0,
            "payout": 0,
            "profit": 0,
            "hit_rate": None,
            "roi": None,
        },
        "3T": {
            "races": 0,
            "hit_races": 0,
            "stake": 0,
            "payout": 0,
            "profit": 0,
            "hit_rate": None,
            "roi": None,
        },
    }

    for row in rows:

        bet_type = row[
            "bet_type"
        ]

        races = (
            row["races"]
            or 0
        )

        hit_races = (
            row["hit_races"]
            or 0
        )

        stake = (
            row["total_stake"]
            or 0
        )

        payout = (
            row["total_payout"]
            or 0
        )

        profit = (
            row["total_profit"]
            or 0
        )

        summary[
            bet_type
        ] = {
            "races":
                races,
            "hit_races":
                hit_races,
            "stake":
                stake,
            "payout":
                payout,
            "profit":
                profit,
            "hit_rate":
                (
                    round(
                        hit_races
                        / races,
                        4,
                    )
                    if races
                    else None
                ),
            "roi":
                (
                    round(
                        payout
                        / stake,
                        4,
                    )
                    if stake
                    else None
                ),
        }

    return summary


def calibration_report():
    init_db()

    buckets = [
        (0.00, 0.05),
        (0.05, 0.10),
        (0.10, 0.15),
        (0.15, 0.20),
        (0.20, 0.30),
        (0.30, 1.01),
    ]

    samples = []

    with connect() as con:
        rows = con.execute(
            """
            SELECT
                p.bet_type,
                p.selections_json,
                r.winning_2t,
                r.winning_3t
            FROM prediction_records p
            JOIN race_results r
              ON p.race_id = r.race_id
            WHERE p.verified=1
            """
        ).fetchall()

    for row in rows:

        selections = json.loads(
            row[
                "selections_json"
            ]
        )

        winner = (
            row[
                "winning_2t"
            ]
            if row[
                "bet_type"
            ] == "2T"
            else row[
                "winning_3t"
            ]
        )

        for item in selections:
            samples.append(
                {
                    "bet_type":
                        row[
                            "bet_type"
                        ],
                    "probability":
                        item[
                            "probability"
                        ],
                    "hit":
                        (
                            1
                            if item[
                                "selection"
                            ] == winner
                            else 0
                        ),
                }
            )

    result = {}

    for bet_type in (
        "2T",
        "3T",
    ):
        result[
            bet_type
        ] = []

        selected = [
            item
            for item in samples
            if item[
                "bet_type"
            ] == bet_type
        ]

        for low, high in buckets:

            bucket = [
                item
                for item in selected
                if (
                    low
                    <= item[
                        "probability"
                    ]
                    < high
                )
            ]

            count = len(
                bucket
            )

            if count == 0:
                continue

            average_probability = (
                sum(
                    item[
                        "probability"
                    ]
                    for item in bucket
                )
                / count
            )

            actual_hit_rate = (
                sum(
                    item[
                        "hit"
                    ]
                    for item in bucket
                )
                / count
            )

            result[
                bet_type
            ].append(
                {
                    "range":
                        f"{low:.2f}-{high:.2f}",
                    "samples":
                        count,
                    "predicted":
                        round(
                            average_probability,
                            4,
                        ),
                    "actual":
                        round(
                            actual_hit_rate,
                            4,
                        ),
                    "gap":
                        round(
                            actual_hit_rate
                            - average_probability,
                            4,
                        ),
                }
            )

    return result


if __name__ == "__main__":
    init_db()

    print(
        "BACKTEST_ENGINE_READY"
    )

    print(
        report()
    )
