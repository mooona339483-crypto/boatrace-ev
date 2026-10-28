import json
import math
from itertools import permutations
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from boatcast_preview import fetch_preview
from combined_racer_parser import parse_racelist
from probability_model import (
    Boat,
    predict_probabilities,
)


JST = ZoneInfo("Asia/Tokyo")

DB = os.environ.get(
    "DB_PATH",
    "/data/boatrace_ev.sqlite3",
)

MODEL_VERSION = "heuristic-v1"

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


def now_jst():
    return datetime.now(JST)


def init_db():
    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS shadow_prediction_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id TEXT NOT NULL,
                race_date TEXT NOT NULL,
                venue_code TEXT NOT NULL,
                race_no INTEGER NOT NULL,
                race_category TEXT NOT NULL,
                deadline TEXT,
                bet_type TEXT NOT NULL,
                checkpoint_minutes INTEGER NOT NULL,
                actual_minutes REAL NOT NULL,
                odds_snapshot_id INTEGER NOT NULL,
                odds_captured_at TEXT NOT NULL,
                model_version TEXT NOT NULL,
                model_verified INTEGER NOT NULL,
                selections_json TEXT NOT NULL,
                selection_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                recorded_at TEXT NOT NULL,

                UNIQUE(
                    race_id,
                    bet_type,
                    checkpoint_minutes,
                    model_version
                )
            )
            """
        )

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_shadow_race
            ON shadow_prediction_records (
                race_id,
                bet_type,
                checkpoint_minutes
            )
            """
        )


def init_issue_db():
    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS shadow_data_issues (
                race_id TEXT NOT NULL,
                checkpoint_minutes INTEGER NOT NULL,
                bet_type TEXT NOT NULL,
                boat_number INTEGER NOT NULL,
                missing_field TEXT NOT NULL,
                reason TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                observation_scope TEXT NOT NULL,

                PRIMARY KEY (
                    race_id,
                    checkpoint_minutes,
                    bet_type,
                    boat_number,
                    missing_field
                )
            )
            """
        )


def get_checkpoint_pairs():
    with connect() as con:
        rows = con.execute(
            """
            SELECT
                race_id,
                race_date,
                venue_code,
                race_no,
                checkpoint_minutes,

                MAX(
                    CASE
                        WHEN bet_type='2T'
                        THEN snapshot_id
                    END
                ) AS snapshot_2t,

                MAX(
                    CASE
                        WHEN bet_type='3T'
                        THEN snapshot_id
                    END
                ) AS snapshot_3t,

                MAX(
                    CASE
                        WHEN bet_type='2T'
                        THEN actual_minutes
                    END
                ) AS minutes_2t,

                MAX(
                    CASE
                        WHEN bet_type='3T'
                        THEN actual_minutes
                    END
                ) AS minutes_3t,

                MAX(
                    CASE
                        WHEN bet_type='2T'
                        THEN captured_at
                    END
                ) AS captured_2t,

                MAX(
                    CASE
                        WHEN bet_type='3T'
                        THEN captured_at
                    END
                ) AS captured_3t

            FROM odds_checkpoints

            WHERE checkpoint_minutes
                IN (1, 2)

            GROUP BY
                race_id,
                race_date,
                venue_code,
                race_no,
                checkpoint_minutes

            ORDER BY
                race_date,
                race_no,
                checkpoint_minutes DESC
            """
        ).fetchall()

    return rows


def already_recorded(
    race_id,
    bet_type,
    checkpoint,
):
    with connect() as con:
        row = con.execute(
            """
            SELECT 1
            FROM shadow_prediction_records
            WHERE race_id=?
              AND bet_type=?
              AND checkpoint_minutes=?
              AND model_version=?
            LIMIT 1
            """,
            (
                race_id,
                bet_type,
                checkpoint,
                MODEL_VERSION,
            ),
        ).fetchone()

    return row is not None


def
