"""Kurigram (MTProto) side channel.

Aiogram owns getUpdates. This client is started with no_updates so the two
libraries never compete for the same bot updates.
"""

from __future__ import annotations

import logging

from .config import Settings

log = logging.getLogger(__name__)


class KurigramBridge:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = None

    async def start(self) -> None:
        if not self.settings.kurigram_enabled:
            log.info("Kurigram idle: set API_ID and API_HASH to enable MTProto lookups")
            return
        from pyrogram import Client

        kwargs = {
            "name": "summon_mtproto",
            "api_id": self.settings.api_id,
            "api_hash": self.settings.api_hash,
            "no_updates": True,
            "in_memory": not self.settings.session_string,
        }
        if self.settings.session_string:
            kwargs["session_string"] = self.settings.session_string
        else:
            kwargs["bot_token"] = self.settings.bot_token
        self.client = Client(**kwargs)
        await self.client.start()
        me = await self.client.get_me()
        log.info("Kurigram connected as %s", getattr(me, "username", None) or me.id)

    async def stop(self) -> None:
        if self.client is not None:
            await self.client.stop()
            self.client = None

    async def resolve_username(self, username: str) -> int | None:
        if self.client is None:
            return None
        try:
            chat = await self.client.get_chat(username.lstrip("@"))
        except Exception:
            log.exception("Kurigram username lookup failed")
            return None
        return int(chat.id)

    async def custom_emoji_count(self, emoji_id: int) -> int | None:
        if self.client is None:
            return None
        from pyrogram import raw

        try:
            result = await self.client.invoke(
                raw.functions.messages.GetCustomEmojiDocuments(document_id=[emoji_id])
            )
        except Exception:
            log.exception("Kurigram custom emoji lookup failed")
            return None
        return len(result or [])

    async def member_count(self, chat_id: int) -> int | None:
        if self.client is None:
            return None
        try:
            chat = await self.client.get_chat(chat_id)
        except Exception:
            return None
        return getattr(chat, "members_count", None)
