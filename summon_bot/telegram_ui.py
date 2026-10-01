"""Sending helpers that prefer Bot API 9.4–10.2 features and fall back cleanly."""

from __future__ import annotations

from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    InputRichMessage,
    LinkPreviewOptions,
    Message,
    ReactionTypeEmoji,
)

from richgram import rich_to_plain

from .db import MediaCache
from sqlalchemy.ext.asyncio import AsyncSession

LINK_OFF = LinkPreviewOptions(is_disabled=True)


def h(value: object) -> str:
    return escape(str(value), quote=False)


async def send_text(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    ephemeral: bool = False,
    effect_id: str | None = None,
    reply_to: int | None = None,
) -> Message | None:
    kwargs: dict = {
        "reply_markup": reply_markup,
        "link_preview_options": LINK_OFF,
    }
    if effect_id:
        kwargs["message_effect_id"] = effect_id
    if reply_to:
        kwargs["reply_to_message_id"] = reply_to
    private = message.chat.type == "private"
    if ephemeral and not private and message.from_user:
        kwargs["receiver_user_id"] = message.from_user.id
    try:
        return await message.bot.send_message(message.chat.id, text, **kwargs)
    except TelegramBadRequest:
        kwargs.pop("receiver_user_id", None)
        kwargs.pop("message_effect_id", None)
        try:
            return await message.bot.send_message(message.chat.id, text, **kwargs)
        except TelegramBadRequest:
            return None


async def send_rich(message: Message, html: str, reply_markup: InlineKeyboardMarkup | None = None, *, ephemeral: bool = False) -> Message | None:
    from aiogram.types import EphemeralMessageParameters

    kwargs: dict = {"reply_markup": reply_markup}
    if ephemeral and message.chat.type != "private" and message.from_user:
        kwargs["ephemeral_message_parameters"] = EphemeralMessageParameters(receiver_user_id=message.from_user.id)
    try:
        return await message.bot.send_rich_message(
            message.chat.id,
            InputRichMessage(html=html),
            **kwargs,
        )
    except TelegramBadRequest:
        plain = rich_to_plain(html) or html
        return await send_text(message, plain[:4096], reply_markup, ephemeral=ephemeral)


async def _ack(callback: CallbackQuery, text: str | None = None, *, show_alert: bool = False) -> None:
    try:
        if text:
            await callback.answer(text[:180], show_alert=show_alert)
        else:
            await callback.answer()
    except TelegramBadRequest:
        return


async def edit_panel(callback: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    msg = callback.message
    if msg and getattr(msg, "ephemeral_message_id", None):
        try:
            await callback.bot.edit_ephemeral_message_text(
                chat_id=msg.chat.id,
                receiver_user_id=callback.from_user.id,
                ephemeral_message_id=msg.ephemeral_message_id,
                text=text,
                reply_markup=reply_markup,
                link_preview_options=LINK_OFF,
            )
            await _ack(callback)
            return
        except TelegramBadRequest:
            pass
    if msg and getattr(msg, "text", None):
        try:
            await msg.edit_text(text, reply_markup=reply_markup, link_preview_options=LINK_OFF)
            await _ack(callback)
            return
        except TelegramBadRequest as exc:
            if "not modified" in str(exc).lower():
                await _ack(callback)
                return
    await _ack(callback, text, show_alert=True)


async def react(bot: Bot, chat_id: int, message_id: int, emoji: str = "🎉") -> None:
    try:
        await bot.set_message_reaction(chat_id, message_id, [ReactionTypeEmoji(emoji=emoji)], is_big=True)
    except TelegramBadRequest:
        return


async def send_cached_photo(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    cache_key: str,
    path,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    **kwargs,
) -> Message:
    row = await session.get(MediaCache, cache_key)
    photo = row.file_id if row else FSInputFile(str(path))
    try:
        msg = await bot.send_photo(chat_id, photo, caption=caption[:1024], reply_markup=reply_markup, **kwargs)
    except TelegramBadRequest:
        if row is None:
            raise
        await session.delete(row)
        msg = await bot.send_photo(
            chat_id,
            FSInputFile(str(path)),
            caption=caption[:1024],
            reply_markup=reply_markup,
            **kwargs,
        )
        row = None
    if row is None and msg.photo:
        session.add(MediaCache(key=cache_key, file_id=msg.photo[-1].file_id))
    return msg
