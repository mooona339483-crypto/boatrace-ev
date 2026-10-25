
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backtest_engine import (
    init_db,
    record_prediction,
    record_result,
    report,
)


class TestBacktestEngine(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(
            Path(self.temp.name) / "test_backtest.sqlite3"
        )
        init_db(self.db)

        now = datetime.now(timezone.utc)
        self.predicted_at = (
            now - timedelta(minutes=20)
        ).isoformat()
        self.deadline = (
            now - timedelta(minutes=10)
        ).isoformat()

    def tearDown(self):
        self.temp.cleanup()

    def add_prediction(
        self,
        race_id="TEST_RACE_01",
        bet_type="3T",
        selection="1-2-3",
        probability=0.10,
        odds=15.0,
        stake=1000,
        verified=True,
    ):
        record_prediction(
            race_id=race_id,
            bet_type=bet_type,
            selection=selection,
            probability=probability,
            odds=odds,
            stake=stake,
            deadline=self.deadline,
            predicted_at=self.predicted_at,
            source="TEST_ONLY",
            verified=verified,
            db_path=self.db,
        )

    def test_empty_report(self):
        result = report(self.db)

        for bet_type in ("2T", "3T"):
            self.assertEqual(
                result[bet_type]["status"], "UNTESTED"
            )
            self.assertEqual(result[bet_type]["bets"], 0)
            self.assertIsNone(result[bet_type]["roi"])

    def test_unverified_prediction_rejected(self):
        with self.assertRaises(ValueError):
            self.add_prediction(verified=False)

    def test_prediction_after_deadline_rejected(self):
        with self.assertRaises(ValueError):
            record_prediction(
                race_id="TEST_RACE_02",
                bet_type="3T",
                selection="1-2-3",
                probability=0.10,
                odds=15.0,
                stake=1000,
                deadline=self.deadline,
                predicted_at=(
                    datetime.fromisoformat(self.deadline)
                    + timedelta(seconds=1)
                ).isoformat(),
                source="TEST_ONLY",
                verified=True,
                db_path=self.db,
            )

    def test_invalid_selection_rejected(self):
        with self.assertRaises(ValueError):
            self.add_prediction(selection="1-1-3")

    def test_winning_payout(self):
        self.add_prediction(stake=1000)

        record_result(
            race_id="TEST_RACE_01",
            winning_2t="1-2",
            winning_3t="1-2-3",
            payout_2t=500,
            payout_3t=1500,
            db_path=self.db,
        )

        result = report(self.db)["3T"]

        self.assertEqual(result["bets"], 1)
        self.assertEqual(result["hits"], 1)
        self.assertEqual(result["stake"], 1000)
        self.assertEqual(result["payout"], 15000)
        self.assertEqual(result["profit"], 14000)
        self.assertAlmostEqual(result["roi"], 15.0)

    def test_losing_bet(self):
        self.add_prediction(stake=1000)

        record_result(
            race_id="TEST_RACE_01",
            winning_2t="2-1",
            winning_3t="2-1-3",
            payout_2t=400,
            payout_3t=1000,
            db_path=self.db,
        )

        result = report(self.db)["3T"]

        self.assertEqual(result["hits"], 0)
        self.assertEqual(result["payout"], 0)
        self.assertEqual(result["profit"], -1000)
        self.assertEqual(result["roi"], 0.0)

    def test_separate_bet_types(self):
        self.add_prediction(
            bet_type="2T",
            selection="1-2",
            stake=1000,
        )
        self.add_prediction(
            bet_type="3T",
            selection="1-2-3",
            stake=1000,
        )

        record_result(
            race_id="TEST_RACE_01",
            winning_2t="1-2",
            winning_3t="1-2-3",
            payout_2t=500,
            payout_3t=1500,
            db_path=self.db,
        )

        result = report(self.db)

        self.assertEqual(result["2T"]["payout"], 5000)
        self.assertEqual(result["3T"]["payout"], 15000)
        self.assertEqual(result["2T"]["bets"], 1)
        self.assertEqual(result["3T"]["bets"], 1)

    def test_no_result_not_counted(self):
        self.add_prediction()

        result = report(self.db)["3T"]

        self.assertEqual(result["bets"], 0)
        self.assertEqual(result["status"], "UNTESTED")


if __name__ == "__main__":
    unittest.main()
