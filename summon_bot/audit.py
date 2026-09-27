"""Live audit feed to a Telegram log channel and optional MongoDB mirror."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

if TYPE_CHECKING:
    from .config import Settings

log = logging.getLogger(__name__)
_mongo_db = None
_mongo_client = None


async def init_mongo(settings: Settings):
    global _mongo_db, _mongo_client
    if not settings.mongo_uri:
        _mongo_db = None
        return None
    try:
        from motor.motor_asyncio import AsyncIOMotorClient

        _mongo_client = AsyncIOMotorClient(settings.mongo_uri)
        _mongo_db = _mongo_client[settings.mongo_db_name]
        await _mongo_db.audit_events.create_index("at")
        log.info("Mongo audit mirror enabled")
        return _mongo_db
    except Exception:
        log.exception("Mongo audit disabled")
        _mongo_db = None
        return None


async def close_mongo() -> None:
    global _mongo_db, _mongo_client
    if _mongo_client is not None:
        _mongo_client.close()
    _mongo_db = None
    _mongo_client = None


async def audit(bot: Bot | None, settings: Settings, event: str, detail: str = "") -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"<b>{event}</b>\n{detail}\n<code>{stamp}</code>" if detail else f"<b>{event}</b>\n<code>{stamp}</code>"
    if settings.log_channel_id and bot is not None:
        try:
            await bot.send_message(settings.log_channel_id, line[:4096], disable_notification=True)
        except TelegramBadRequest:
            log.warning("log channel send failed")
        except Exception:
            log.exception("log channel error")
    if _mongo_db is not None:
        try:
            await _mongo_db.audit_events.insert_one(
                {"event": event, "detail": detail, "at": datetime.now(timezone.utc)}
            )
        except Exception:
            log.exception("mongo audit write failed")
    log.info("%s | %s", event, detail[:200])
