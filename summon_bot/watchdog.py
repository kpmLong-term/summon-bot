"""Background keep-alive, backup, cleanup, and self-ping loops."""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp
from aiogram import Bot

from .audit import audit
from .backup import run_backup
from .config import Settings
from .db import Database
from .maintenance import cleanup_inactive, count_users

log = logging.getLogger(__name__)
_started_at = time.time()


async def keepalive_loop(settings: Settings) -> None:
    if not settings.keepalive_url:
        return
    url = settings.keepalive_url
    async with aiohttp.ClientSession() as http:
        while True:
            try:
                async with http.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    log.debug("keepalive %s -> %s", url, resp.status)
            except Exception:
                log.warning("keepalive ping failed")
            await asyncio.sleep(max(60, settings.keepalive_seconds))


async def backup_loop(bot: Bot, settings: Settings, database: Database) -> None:
    await asyncio.sleep(30)
    while True:
        try:
            path = await run_backup(settings)
            if path:
                await audit(
                    bot,
                    settings,
                    "Backup",
                    f"Saved {path.name} ({settings.database_backend})",
                )
        except Exception:
            log.exception("backup loop failed")
        await asyncio.sleep(max(3600, settings.backup_interval_hours * 3600))


async def maintenance_loop(bot: Bot, settings: Settings, database: Database) -> None:
    await asyncio.sleep(120)
    while True:
        try:
            async with database.session() as session:
                removed = await cleanup_inactive(session, settings)
                total = await count_users(session)
            if removed:
                await audit(
                    bot,
                    settings,
                    "Cleanup",
                    f"Removed {removed} inactive accounts · {total} players remain",
                )
        except Exception:
            log.exception("maintenance loop failed")
        await asyncio.sleep(max(3600, settings.maintenance_interval_hours * 3600))


async def heartbeat_loop(bot: Bot, settings: Settings) -> None:
    while True:
        uptime = int(time.time() - _started_at)
        await audit(
            bot,
            settings,
            "Heartbeat",
            f"Uptime {uptime // 3600}h {(uptime % 3600) // 60}m · mode {'webhook' if settings.webhook_url else 'polling'}",
        )
        await asyncio.sleep(max(300, settings.heartbeat_minutes * 60))
