import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

STEPS = [
    "collector.py",
    "market_collector.py",
    "parser.py",
    "odds_mapper.py",
    "racer_data_probe.py",
    "model_probe.py",
    "result_collector.py",
]


def main():
    print(
        "PIPELINE_START",
        datetime.now(JST).isoformat(),
        flush=True,
    )

    for script in STEPS:
        print(
            "STEP_START",
            script,
            flush=True,
        )

        result = subprocess.run(
            [sys.executable, script],
            check=False,
        )

        if result.returncode != 0:
            print(
                "STEP_FAILED",
                script,
                result.returncode,
                flush=True,
            )
            sys.exit(
                result.returncode
            )

        print(
            "STEP_DONE",
            script,
            flush=True,
        )

    print(
        "PIPELINE_DONE",
        datetime.now(JST).isoformat(),
        flush=True,
    )


if __name__ == "__main__":
    main()
