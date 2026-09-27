"""One database transaction per update, plus ban and flood guards."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, User as TgUser

from .config import Settings
from .db import Database
from .game import SPAM_BAN, SPAM_WARN
from .repo import get_or_create_user

_HITS: dict[int, deque[float]] = defaultdict(deque)


def extract_user(event: TelegramObject) -> TgUser | None:
    if isinstance(event, Update):
        if event.guest_message is not None:
            return event.guest_message.guest_bot_caller_user or event.guest_message.from_user
        if event.subscription is not None:
            return event.subscription.user
        for name in (
            "message",
            "edited_message",
            "callback_query",
            "inline_query",
            "pre_checkout_query",
            "my_chat_member",
            "chat_join_request",
            "purchased_paid_media",
            "business_message",
            "poll_answer",
        ):
            obj = getattr(event, name, None)
            if obj is None:
                continue
            user = getattr(obj, "from_user", None) or getattr(obj, "user", None)
            if user is not None:
                return user
        return None
    return getattr(event, "from_user", None)


def _actionable(event: Update) -> bool:
    if event.callback_query or event.inline_query or event.pre_checkout_query:
        return True
    message = event.message
    return bool(message and message.text and message.text.startswith("/"))


class DbMiddleware(BaseMiddleware):
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def __call__(self, handler, event: TelegramObject, data: dict):
        async with self.db.session() as session:
            data["session"] = session
            data["settings"] = self.settings
            tg_user = extract_user(event)
            player = None
            if isinstance(tg_user, TgUser) and not tg_user.is_bot:
                player = await get_or_create_user(session, tg_user, self.settings)
                if player.banned and not self.settings.is_owner(tg_user.id):
                    if isinstance(event, Update) and _actionable(event):
                        bot = data["bot"]
                        text = "You are banned from this bot."
                        try:
                            if event.callback_query:
                                await event.callback_query.answer(text, show_alert=True)
                            elif event.message:
                                await bot.send_message(event.message.chat.id, text, receiver_user_id=tg_user.id)
                        except Exception:
                            pass
                    return None
                if isinstance(event, Update) and event.message and event.message.text and event.message.text.startswith("/"):
                    if not self.settings.is_owner(tg_user.id) and _flooding(tg_user.id):
                        player.banned = True
                        try:
                            await data["bot"].send_message(
                                event.message.chat.id,
                                "Flooding commands got this account banned. Ask a sudo to /unban you.",
                                receiver_user_id=tg_user.id,
                            )
                        except Exception:
                            pass
                        return None
            data["player"] = player
            return await handler(event, data)


def _flooding(user_id: int) -> bool:
    now = time.monotonic()
    bucket = _HITS[user_id]
    bucket.append(now)
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) == SPAM_WARN:
        return False
    return len(bucket) >= SPAM_BAN
