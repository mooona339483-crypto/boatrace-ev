
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backtest_engine import (
    init_db,
    record_prediction,
    record_result,
)
from validation_report import validation_report


class TestValidationReport(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(
            Path(self.temp.name) / "validation_test.sqlite3"
        )
        init_db(self.db)

        now = datetime.now(timezone.utc)
        self.predicted_at = (
            now - timedelta(minutes=10)
        ).isoformat()
        self.deadline = (
            now + timedelta(minutes=30)
        ).isoformat()

    def tearDown(self):
        self.temp.cleanup()

    def add_prediction(
        self,
        race_id="TEST_RACE_01",
        bet_type="3T",
        selection="1-2-3",
        stake=1000,
        verified=True,
    ):
        record_prediction(
            race_id=race_id,
            bet_type=bet_type,
            selection=selection,
            probability=0.10,
            odds=15.0,
            stake=stake,
            deadline=self.deadline,
            predicted_at=self.predicted_at,
            source="UNIT_TEST",
            verified=verified,
            db_path=self.db,
        )

    def add_result(
        self,
        race_id="TEST_RACE_01",
        winning_2t="1-2",
        winning_3t="1-2-3",
        payout_2t=500,
        payout_3t=1500,
    ):
        record_result(
            race_id=race_id,
            winning_2t=winning_2t,
            winning_3t=winning_3t,
            payout_2t=payout_2t,
            payout_3t=payout_3t,
            db_path=self.db,
        )

    def test_empty_database(self):
        result = validation_report(self.db)

        self.assertEqual(
            result["2T"]["status"],
            "UNVERIFIED",
        )
        self.assertEqual(
            result["3T"]["status"],
            "UNVERIFIED",
        )
        self.assertIsNone(result["3T"]["roi"])

    def test_missing_database(self):
        missing = str(
            Path(self.temp.name) / "missing.sqlite3"
        )
        result = validation_report(missing)

        self.assertIsNone(result["2T"]["roi"])
        self.assertIsNone(result["3T"]["roi"])

    def test_pending_result(self):
        self.add_prediction()

        report = validation_report(self.db)["3T"]

        self.assertEqual(
            report["status"],
            "PARTIAL_RESULTS",
        )
        self.assertEqual(report["pending_bets"], 1)
        self.assertEqual(report["pending_races"], 1)
        self.assertEqual(report["bets"], 0)
        self.assertIsNone(report["roi"])

    def test_winning_bet(self):
        self.add_prediction()
        self.add_result()

        report = validation_report(self.db)["3T"]

        self.assertEqual(report["bets"], 1)
        self.assertEqual(report["hits"], 1)
        self.assertEqual(report["stake"], 1000)
        self.assertEqual(report["payout"], 15000)
        self.assertEqual(report["profit"], 14000)
        self.assertAlmostEqual(report["roi"], 15.0)

    def test_losing_bet(self):
        self.add_prediction(
            selection="1-3-2"
        )
        self.add_result()

        report = validation_report(self.db)["3T"]

        self.assertEqual(report["bets"], 1)
        self.assertEqual(report["hits"], 0)
        self.assertEqual(report["payout"], 0)
        self.assertEqual(report["profit"], -1000)
        self.assertEqual(report["roi"], 0.0)

    def test_separate_bet_types(self):
        self.add_prediction(
            bet_type="2T",
            selection="1-2",
        )
        self.add_prediction(
            bet_type="3T",
            selection="1-2-3",
        )
        self.add_result()

        report = validation_report(self.db)

        self.assertEqual(report["2T"]["bets"], 1)
        self.assertEqual(report["3T"]["bets"], 1)
        self.assertEqual(report["2T"]["payout"], 5000)
        self.assertEqual(report["3T"]["payout"], 15000)

    def test_hit_rate(self):
        self.add_prediction(
            race_id="RACE_A",
            selection="1-2-3",
        )
        self.add_prediction(
            race_id="RACE_B",
            selection="1-3-2",
        )
        self.add_result(race_id="RACE_A")
        self.add_result(race_id="RACE_B")

        report = validation_report(self.db)["3T"]

        self.assertEqual(report["bets"], 2)
        self.assertEqual(report["hits"], 1)
        self.assertAlmostEqual(
            report["hit_rate"], 0.5
        )

    def test_pending_and_completed(self):
        self.add_prediction(
            race_id="DONE_RACE",
        )
        self.add_prediction(
            race_id="PENDING_RACE",
        )
        self.add_result(race_id="DONE_RACE")

        report = validation_report(self.db)["3T"]

        self.assertEqual(
            report["status"],
            "PARTIAL_RESULTS",
        )
        self.assertEqual(report["bets"], 1)
        self.assertEqual(report["pending_bets"], 1)
        self.assertEqual(report["pending_races"], 1)
        self.assertEqual(report["races"], 1)

    def test_multiple_bets_same_race(self):
        self.add_prediction(
            selection="1-2-3",
        )
        self.add_prediction(
            selection="1-3-2",
        )
        self.add_result()

        report = validation_report(self.db)["3T"]

        self.assertEqual(report["races"], 1)
        self.assertEqual(report["bets"], 2)
        self.assertEqual(report["hits"], 1)
        self.assertEqual(report["stake"], 2000)

    def test_payout_calculation(self):
        self.add_prediction(stake=2000)
        self.add_result(payout_3t=1800)

        report = validation_report(self.db)["3T"]

        self.assertEqual(report["payout"], 36000)
        self.assertEqual(report["profit"], 34000)
        self.assertAlmostEqual(report["roi"], 18.0)


if __name__ == "__main__":
    unittest.main()
