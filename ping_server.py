#!/usr/bin/env python3
"""Ping the local health endpoint so free hosts keep the bot process warm."""

from __future__ import annotations

import os
import time
import urllib.request

URL = os.getenv("KEEPALIVE_URL", "http://127.0.0.1:8080/ping")
INTERVAL = int(os.getenv("KEEPALIVE_SECONDS", "300") or "300")


def main() -> None:
    while True:
        try:
            with urllib.request.urlopen(URL, timeout=20) as resp:
                print(resp.read().decode()[:80], resp.status)
        except Exception as exc:
            print("ping failed", exc)
        time.sleep(max(60, INTERVAL))


if __name__ == "__main__":
    main()
