
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import run_pipeline


class TestPipeline(unittest.TestCase):

    def test_execution_order(self):
        calls = []

        def fake_run(command, check=False):
            calls.append(command[1])
            return SimpleNamespace(returncode=0)

        with patch.object(
            run_pipeline.subprocess,
            "run",
            side_effect=fake_run
        ):
            run_pipeline.main()

        self.assertEqual(
            calls,
            [
                "collector.py",
                "market_collector.py",
                "parser.py",
                "odds_mapper.py",
            ]
        )

    def test_stop_on_failure(self):
        calls = []

        def fake_run(command, check=False):
            calls.append(command[1])
            code = 1 if len(calls) == 2 else 0
            return SimpleNamespace(returncode=code)

        with patch.object(
            run_pipeline.subprocess,
            "run",
            side_effect=fake_run
        ):
            with self.assertRaises(SystemExit):
                run_pipeline.main()

        self.assertEqual(
            calls,
            ["collector.py", "market_collector.py"]
        )


if __name__ == "__main__":
    unittest.main()
