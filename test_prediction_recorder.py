
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from prediction_recorder import (
    init_db,
    record_prediction,
    get_records,
)


class TestPredictionRecorder(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(
            Path(self.temp.name) / "test_records.sqlite3"
        )
        init_db(self.db)

        self.deadline = (
            datetime.now(timezone.utc)
            + timedelta(hours=1)
        ).isoformat()

    def tearDown(self):
        self.temp.cleanup()

    def selection(self, **changes):
        item = {
            "selection": "1-2-3",
            "probability": 0.10,
            "odds": 15.0,
            "stake": 1000,
            "verified": True,
        }
        item.update(changes)
        return item

    def save(
        self,
        race_id="TEST_RACE_01",
        bet_type="3T",
        race_category="mixed",
        deadline=None,
        selections=None,
    ):
        return record_prediction(
            race_id=race_id,
            bet_type=bet_type,
            race_category=race_category,
            deadline=deadline or self.deadline,
            model_version="TEST_MODEL",
            selections=(
                selections
                if selections is not None
                else [self.selection()]
            ),
            db_path=self.db,
        )

    def test_valid_record(self):
        result = self.save()

        self.assertEqual(
            result["status"],
            "VIRTUAL_RECORDED",
        )
        self.assertEqual(result["total_stake"], 1000)
        self.assertEqual(len(get_records(self.db)), 1)

    def test_after_deadline_rejected(self):
        deadline = (
            datetime.now(timezone.utc)
            - timedelta(minutes=1)
        ).isoformat()

        with self.assertRaises(ValueError):
            self.save(deadline=deadline)

    def test_duplicate_race_rejected(self):
        self.save()

        with self.assertRaises(sqlite3.IntegrityError):
            self.save()

        self.assertEqual(len(get_records(self.db)), 1)

    def test_separate_bet_types(self):
        self.save()

        self.save(
            bet_type="2T",
            selections=[
                self.selection(selection="1-2")
            ],
        )

        records = get_records(self.db)
        self.assertEqual(len(records), 2)

    def test_budget_exceeded_rejected(self):
        with self.assertRaises(ValueError):
            self.save(
                selections=[
                    self.selection(stake=10100)
                ]
            )

    def test_invalid_stake_rejected(self):
        with self.assertRaises(ValueError):
            self.save(
                selections=[
                    self.selection(stake=150)
                ]
            )

    def test_unverified_rejected(self):
        with self.assertRaises(ValueError):
            self.save(
                selections=[
                    self.selection(verified=False)
                ]
            )

    def test_female_only_rejected(self):
        with self.assertRaises(ValueError):
            self.save(race_category="female_only")

    def test_duplicate_selection_rejected(self):
        with self.assertRaises(ValueError):
            self.save(
                selections=[
                    self.selection(),
                    self.selection(),
                ]
            )

    def test_invalid_selection_rejected(self):
        with self.assertRaises(ValueError):
            self.save(
                selections=[
                    self.selection(selection="1-1-3")
                ]
            )

    def test_invalid_probability_rejected(self):
        with self.assertRaises(ValueError):
            self.save(
                selections=[
                    self.selection(probability=1.5)
                ]
            )

    def test_invalid_odds_rejected(self):
        with self.assertRaises(ValueError):
            self.save(
                selections=[
                    self.selection(odds=0.5)
                ]
            )

    def test_no_selections_rejected(self):
        with self.assertRaises(ValueError):
            self.save(selections=[])

    def test_budget_exactly_10000(self):
        result = self.save(
            selections=[
                self.selection(
                    selection="1-2-3",
                    stake=5000,
                ),
                self.selection(
                    selection="1-3-2",
                    stake=5000,
                ),
            ]
        )
        self.assertEqual(result["total_stake"], 10000)

    def test_record_timestamp_exists(self):
        self.save()
        records = get_records(self.db)

        self.assertEqual(len(records), 1)
        recorded = datetime.fromisoformat(
            records[0]["recorded_at"]
        )
        self.assertIsNotNone(recorded.tzinfo)


if __name__ == "__main__":
    unittest.main()
