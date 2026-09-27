"""Group utility commands: tagall, kick, mute helpers."""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import GroupMember, User
from ..repo import has_power
from ..telegram_ui import h, send_text

router = Router(name="manage")


def _mentions(members: list[GroupMember]) -> str:
    chunks = []
    for member in members:
        label = member.first_name or "player"
        if member.username:
            chunks.append(f'<a href="tg://user?id={member.user_id}">{h(label)}</a>')
        else:
            chunks.append(f'<a href="tg://user?id={member.user_id}">{h(label)}</a>')
    return ", ".join(chunks)


@router.message(Command("tagall", "all", "mentionall"))
async def tagall_cmd(
    message: Message,
    session: AsyncSession,
    player: User,
    settings: Settings,
    bot: Bot,
) -> None:
    if message.chat.type == "private":
        await send_text(message, "Use this inside a group.", ephemeral=True)
        return
    allowed = settings.is_owner(player.id) or await has_power(session, settings, player.id, "moderate")
    if not allowed:
        try:
            member = await bot.get_chat_member(message.chat.id, player.id)
            allowed = member.status in {"administrator", "creator"}
        except Exception:
            allowed = False
    if not allowed:
        await send_text(message, "Only sudo or group admins can tag everyone.", ephemeral=True)
        return
    parts = (message.text or "").split(maxsplit=1)
    body = parts[1] if len(parts) > 1 else "📢 Attention"
    rows = (
        await session.scalars(
            select(GroupMember)
            .where(GroupMember.chat_id == message.chat.id)
            .order_by(GroupMember.last_seen.desc())
            .limit(settings.tagall_limit)
        )
    ).all()
    if not rows:
        await send_text(message, "No tracked members yet. Let people chat first.", ephemeral=True)
        return
    text = f"{h(body)}\n\n{_mentions(list(rows))}"
    await message.answer(text[:4096], disable_notification=False)


@router.message(Command("kick"))
async def kick_cmd(message: Message, session: AsyncSession, player: User, settings: Settings, bot: Bot) -> None:
    if not await has_power(session, settings, player.id, "moderate"):
        await send_text(message, "Sudo only.", ephemeral=True)
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await send_text(message, "Reply to the member you want to kick.", ephemeral=True)
        return
    target = message.reply_to_message.from_user
    if settings.is_owner(target.id):
        await send_text(message, "Cannot kick the owner.", ephemeral=True)
        return
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await bot.unban_chat_member(message.chat.id, target.id, only_if_banned=True)
        await send_text(message, f"Kicked {h(target.full_name)}.")
    except Exception as exc:
        await send_text(message, f"Kick failed: {h(exc)}", ephemeral=True)


@router.message(Command("pin"))
async def pin_cmd(message: Message, session: AsyncSession, player: User, settings: Settings, bot: Bot) -> None:
    if not await has_power(session, settings, player.id, "moderate"):
        await send_text(message, "Sudo only.", ephemeral=True)
        return
    if not message.reply_to_message:
        await send_text(message, "Reply to the message you want pinned.", ephemeral=True)
        return
    try:
        await bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id, disable_notification=True)
        await send_text(message, "Pinned.")
    except Exception as exc:
        await send_text(message, f"Pin failed: {h(exc)}", ephemeral=True)
