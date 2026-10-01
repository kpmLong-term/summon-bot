"""Group utility commands: tagall, kick, mute helpers."""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import ChatPermissions, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import Group, GroupMember, User
from ..repo import ensure_group
from ..repo import has_power
from ..audit import audit, staff_detail
from ..recent import forget, recent_ids
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


async def _moderate(session: AsyncSession, settings: Settings, player: User) -> bool:
    return await has_power(session, settings, player.id, "moderate")


@router.message(Command("mute"))
async def mute_cmd(message: Message, session: AsyncSession, player: User, settings: Settings, bot: Bot) -> None:
    if not await _moderate(session, settings, player):
        await send_text(message, "Sudo only.", ephemeral=True)
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await send_text(message, "Reply to the member you want to mute.", ephemeral=True)
        return
    target = message.reply_to_message.from_user
    if settings.is_owner(target.id):
        await send_text(message, "Cannot mute the owner.", ephemeral=True)
        return
    try:
        await bot.restrict_chat_member(message.chat.id, target.id, ChatPermissions(can_send_messages=False))
        await send_text(message, f"Muted {h(target.full_name)}.")
        from ..audit import audit

        await audit(bot, settings, "Mute", f"{target.id} in {message.chat.id}")
    except Exception as exc:
        await send_text(message, f"Mute failed: {h(exc)}", ephemeral=True)


@router.message(Command("unmute"))
async def unmute_cmd(message: Message, session: AsyncSession, player: User, settings: Settings, bot: Bot) -> None:
    if not await _moderate(session, settings, player):
        await send_text(message, "Sudo only.", ephemeral=True)
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await send_text(message, "Reply to the member you want to unmute.", ephemeral=True)
        return
    target = message.reply_to_message.from_user
    open_chat = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )
    try:
        await bot.restrict_chat_member(message.chat.id, target.id, open_chat)
        await send_text(message, f"Unmuted {h(target.full_name)}.")
        from ..audit import audit

        await audit(bot, settings, "Unmute", f"{target.id} in {message.chat.id}")
    except Exception as exc:
        await send_text(message, f"Unmute failed: {h(exc)}", ephemeral=True)


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


async def _group_admin(message: Message, session: AsyncSession, player: User, settings: Settings, bot: Bot) -> bool:
    if message.chat.type == "private":
        await send_text(message, "Use this inside a group.", ephemeral=True)
        return False
    if settings.is_owner(player.id) or await has_power(session, settings, player.id, "moderate"):
        return True
    try:
        member = await bot.get_chat_member(message.chat.id, player.id)
        if member.status in {"administrator", "creator"}:
            return True
    except Exception:
        pass
    await send_text(message, "Only a group admin, sudo, or the owner can do that.", ephemeral=True)
    return False


@router.message(Command("setwelcome"))
async def setwelcome_cmd(message: Message, session: AsyncSession, player: User, settings: Settings, bot: Bot) -> None:
    if not await _group_admin(message, session, player, settings, bot):
        return
    text = (message.text or "").split(maxsplit=1)
    if len(text) < 2:
        await send_text(message, "Usage: /setwelcome Hello {name} in {chat}", ephemeral=True)
        return
    group = await ensure_group(session, message.chat.id, message.chat.title or "", settings)
    group.welcome = text[1][:500]
    await send_text(message, "Welcome saved. Placeholders: {name} {username} {chat}")
    await audit(bot, settings, "Welcome set", staff_detail(player.id, message.chat.id))


@router.message(Command("clearwelcome"))
async def clearwelcome_cmd(message: Message, session: AsyncSession, player: User, settings: Settings, bot: Bot) -> None:
    if not await _group_admin(message, session, player, settings, bot):
        return
    group = await session.get(Group, message.chat.id)
    if group:
        group.welcome = ""
    await send_text(message, "Welcome cleared.")
    await audit(bot, settings, "Welcome cleared", staff_detail(player.id, message.chat.id))


@router.message(Command("purge"))
async def purge_cmd(message: Message, session: AsyncSession, player: User, settings: Settings, bot: Bot) -> None:
    if not await _group_admin(message, session, player, settings, bot):
        return
    parts = (message.text or "").split()
    limit = 10
    if len(parts) > 1 and parts[1].isdigit():
        limit = max(1, min(25, int(parts[1])))
    ids = recent_ids(message.chat.id, limit)
    if message.reply_to_message:
        ids.append(message.reply_to_message.message_id)
    ids.append(message.message_id)
    removed = 0
    for message_id in dict.fromkeys(ids):
        try:
            await bot.delete_message(message.chat.id, message_id)
            removed += 1
        except Exception:
            continue
    forget(message.chat.id, ids)
    await audit(bot, settings, "Purge", staff_detail(player.id, message.chat.id, f"deleted {removed}"))


@router.message(Command("lock"))
async def lock_cmd(message: Message, session: AsyncSession, player: User, settings: Settings, bot: Bot) -> None:
    if not await _group_admin(message, session, player, settings, bot):
        return
    try:
        await bot.set_chat_permissions(message.chat.id, ChatPermissions(can_send_messages=False))
        await send_text(message, "Chat locked. Members cannot send messages.")
        await audit(bot, settings, "Chat locked", staff_detail(player.id, message.chat.id))
    except Exception as exc:
        await send_text(message, f"Lock failed: {h(exc)}", ephemeral=True)


@router.message(Command("unlock"))
async def unlock_cmd(message: Message, session: AsyncSession, player: User, settings: Settings, bot: Bot) -> None:
    if not await _group_admin(message, session, player, settings, bot):
        return
    open_chat = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )
    try:
        await bot.set_chat_permissions(message.chat.id, open_chat)
        await send_text(message, "Chat unlocked.")
        await audit(bot, settings, "Chat unlocked", staff_detail(player.id, message.chat.id))
    except Exception as exc:
        await send_text(message, f"Unlock failed: {h(exc)}", ephemeral=True)


@router.message(Command("warns"))
async def warns_cmd(message: Message, session: AsyncSession, player: User, settings: Settings, bot: Bot) -> None:
    if not await _group_admin(message, session, player, settings, bot):
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await send_text(message, "Reply to a member to see their warnings.", ephemeral=True)
        return
    from ..db import Warning

    target = message.reply_to_message.from_user
    rows = (
        await session.scalars(
            select(Warning)
            .where(Warning.chat_id == message.chat.id, Warning.user_id == target.id)
            .order_by(Warning.id.desc())
            .limit(8)
        )
    ).all()
    if not rows:
        await send_text(message, f"{h(target.full_name)} has no warnings here.", ephemeral=True)
        return
    lines = [f"• {h(row.reason)}" for row in rows]
    await send_text(message, f"<b>{h(target.full_name)}</b> · {len(rows)} shown\n" + "\n".join(lines), ephemeral=True)


@router.message(Command("setwarns"))
async def setwarns_cmd(message: Message, session: AsyncSession, player: User, settings: Settings, bot: Bot) -> None:
    if not await _group_admin(message, session, player, settings, bot):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await send_text(message, "Usage: /setwarns 3", ephemeral=True)
        return
    limit = max(1, min(8, int(parts[1])))
    group = await ensure_group(session, message.chat.id, message.chat.title or "", settings)
    group.warn_limit = limit
    await send_text(message, f"This group auto-bans at {limit} warnings.")
    await audit(bot, settings, "Warn limit", staff_detail(player.id, message.chat.id, str(limit)))
