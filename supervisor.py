"""Restart the bot after a crash. Leave AUTO_RESTART_MINUTES at 0 unless you must recycle."""

from __future__ import annotations

import os
import subprocess
import sys
import time


def main() -> None:
    minutes = int(os.getenv("AUTO_RESTART_MINUTES", "0") or "0")
    delay = int(os.getenv("RESTART_DELAY_SECONDS", "5") or "5")
    while True:
        started = time.monotonic()
        completed = subprocess.run([sys.executable, "-m", "summon_bot"], cwd=os.path.dirname(__file__))
        if completed.returncode == 0 and minutes <= 0:
            return
        if minutes > 0 and (time.monotonic() - started) >= minutes * 60 and completed.returncode == 0:
            time.sleep(delay)
            continue
        time.sleep(delay)


if __name__ == "__main__":
    main()
