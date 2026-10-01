#!/usr/bin/env python3
"""Ping the local health endpoint so free hosts keep the bot process warm."""

from __future__ import annotations

import os
import time
import urllib.request

from summon_bot.config import resolve_keepalive_url

URL = resolve_keepalive_url(os.getenv("KEEPALIVE_URL", ""), int(os.getenv("PORT", "8080") or "8080"))
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
