"""Live audit feed to a Telegram log channel and optional MongoDB mirror."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InputRichMessage
from richgram import rich_to_plain

from .richfmt import log_html

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


def staff_detail(actor_id: int, chat_id: int, note: str = "") -> str:
    line = f"by {actor_id} · chat {chat_id}"
    if note:
        line = f"{line} · {note}"
    return line


def mongo_status() -> str:
    return "on" if _mongo_db is not None else "off"


async def audit(bot: Bot | None, settings: Settings, event: str, detail: str = "") -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    html = log_html(event, detail, stamp)
    if settings.log_channel_id and bot is not None:
        try:
            await bot.send_rich_message(
                settings.log_channel_id,
                InputRichMessage(html=html),
                disable_notification=True,
            )
        except TelegramBadRequest:
            try:
                await bot.send_message(
                    settings.log_channel_id,
                    rich_to_plain(html)[:4096],
                    disable_notification=True,
                )
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
