"""Sudo and owner tools."""

from __future__ import annotations

import asyncio
import hmac
import os

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import Alias, Card, Character, Group, Spawn, Sudo, User
from ..game import RARITY_BY_KEY, format_duration, normalize_name, now_ts, rarity_from_text
from ..audit import audit
from ..keyboards import confirm_keyboard, copy_keyboard, owner_keyboard
from ..repo import (
    add_warning,
    adjust_balance,
    clear_user_cards,
    create_code,
    ensure_group,
    global_counts,
    has_power,
    set_weight,
    weights_for,
)
from ..telegram_ui import edit_panel, h, send_text

router = Router(name="staff")


class Panel(StatesGroup):
    wait_password = State()


async def _deny(message: Message) -> None:
    await send_text(message, "You cannot use that command.", ephemeral=True)


@router.message(Command("ban"))
async def ban_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not await has_power(session, settings, player.id, "moderate"):
        await _deny(message)
        return
    target = message.reply_to_message.from_user if message.reply_to_message and message.reply_to_message.from_user else None
    if target is None:
        await send_text(message, "Reply to the user you want to ban.", ephemeral=True)
        return
    if settings.is_owner(target.id):
        await send_text(message, "The owner cannot be banned.", ephemeral=True)
        return
    row = await session.get(User, target.id)
    if row is None:
        await send_text(message, "That user has not started the bot.", ephemeral=True)
        return
    row.banned = True
    await send_text(message, f"Banned {h(target.full_name)}.")
    await audit(message.bot, settings, "Ban", f"{target.id} in {message.chat.id}")


@router.message(Command("unban"))
async def unban_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not await has_power(session, settings, player.id, "moderate"):
        await _deny(message)
        return
    parts = (message.text or "").split()
    target_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    elif len(parts) > 1 and parts[1].isdigit():
        target_id = int(parts[1])
    if target_id is None:
        await send_text(message, "Reply to a user or pass an id.", ephemeral=True)
        return
    row = await session.get(User, target_id)
    if row is None:
        await send_text(message, "Unknown user.", ephemeral=True)
        return
    row.banned = False
    await send_text(message, f"Unbanned {target_id}.")


@router.message(Command("warn"))
async def warn_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not await has_power(session, settings, player.id, "moderate"):
        await _deny(message)
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await send_text(message, "Reply to the user you want to warn.", ephemeral=True)
        return
    reason = (message.text or "").split(maxsplit=1)
    text = reason[1] if len(reason) > 1 else "no reason"
    count = await add_warning(session, message.chat.id, message.reply_to_message.from_user.id, text)
    await send_text(message, f"Warning {count} for {h(message.reply_to_message.from_user.full_name)}: {h(text)}")


@router.message(Command("spawn"))
async def spawn_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if message.chat.type == "private":
        await send_text(message, "Spawns happen in groups.", ephemeral=True)
        return
    if not await has_power(session, settings, player.id, "spawn"):
        await _deny(message)
        return
    group = await ensure_group(session, message.chat.id, message.chat.title or "", settings)
    group.message_count = group.spawn_every
    await send_text(message, "The next chat message will spawn a character.")


@router.message(Command("checkspawn"))
async def checkspawn_cmd(message: Message, session: AsyncSession, settings: Settings) -> None:
    group = await session.get(Group, message.chat.id)
    spawn = await session.get(Spawn, message.chat.id)
    if group is None:
        await send_text(message, "This chat is not registered. Send a message or /savegroup.", ephemeral=True)
        return
    extra = ""
    if spawn and spawn.expires_at > now_ts():
        extra = f"\nA spawn is live for {format_duration(spawn.expires_at - now_ts())}."
    await send_text(
        message,
        f"Progress {group.message_count}/{group.spawn_every}. Enabled {group.enabled}.{extra}",
        ephemeral=True,
    )


@router.message(Command("changetime"))
async def changetime_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not await has_power(session, settings, player.id, "spawn"):
        await _deny(message)
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await send_text(message, "Use /changetime &lt;messages between spawns&gt;.", ephemeral=True)
        return
    every = max(5, min(5000, int(parts[1])))
    group = await ensure_group(session, message.chat.id, message.chat.title or "", settings)
    group.spawn_every = every
    await send_text(message, f"Spawn interval is now {every} messages.")


@router.message(Command("chance"))
async def chance_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not await has_power(session, settings, player.id, "spawn"):
        await _deny(message)
        return
    raw = (message.text or "").split(maxsplit=2)
    if len(raw) < 3 or not raw[-1].isdigit():
        await send_text(message, "Use /chance &lt;rarity&gt; &lt;weight&gt;.", ephemeral=True)
        return
    rarity = rarity_from_text(raw[1])
    if rarity is None:
        await send_text(message, "Unknown rarity.", ephemeral=True)
        return
    chat_id = message.chat.id if message.chat.type != "private" else 0
    await set_weight(session, chat_id, rarity.key, max(0, min(10000, int(raw[2]))))
    await send_text(message, f"{h(rarity.label)} weight is now {int(raw[2])} for chat {chat_id}.")


@router.message(Command("chancelist", "clist"))
async def chancelist_cmd(message: Message, session: AsyncSession) -> None:
    chat_id = message.chat.id if message.chat.type != "private" else 0
    weights = await weights_for(session, chat_id)
    lines = ["<b>Weights</b>"] + [f"{h(RARITY_BY_KEY[key].label)}: {weight}" for key, weight in weights if key in RARITY_BY_KEY]
    await send_text(message, "\n".join(lines), ephemeral=True)


@router.message(Command("sudolist"))
async def sudolist_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id) and not await has_power(session, settings, player.id, "moderate"):
        await _deny(message)
        return
    rows = (await session.scalars(select(Sudo))).all()
    if not rows:
        await send_text(message, "No sudo users.", ephemeral=True)
        return
    lines = ["<b>Sudo</b>"]
    for row in rows:
        flags = ",".join(name for name in ("moderate", "spawn", "chars", "economy") if getattr(row, name))
        lines.append(f"{row.user_id} · {h(flags)}")
    await send_text(message, "\n".join(lines), ephemeral=True)


@router.message(Command("addsudo"))
async def addsudo_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await _deny(message)
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await send_text(message, "Use /addsudo &lt;user id&gt; [moderate,spawn,chars,economy].", ephemeral=True)
        return
    flags = set(parts[2].split(",")) if len(parts) > 2 else {"moderate", "spawn"}
    row = await session.get(Sudo, int(parts[1]))
    if row is None:
        row = Sudo(user_id=int(parts[1]))
        session.add(row)
    for name in ("moderate", "spawn", "chars", "economy"):
        setattr(row, name, name in flags)
    await send_text(message, f"Sudo updated for {parts[1]}.", ephemeral=True)


@router.message(Command("rmsudo", "editsudo"))
async def rmsudo_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await _deny(message)
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await send_text(message, "Use /rmsudo &lt;user id&gt;.", ephemeral=True)
        return
    row = await session.get(Sudo, int(parts[1]))
    if row:
        await session.delete(row)
    await send_text(message, "Sudo removed.", ephemeral=True)


@router.message(Command("addchar"))
async def addchar_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not await has_power(session, settings, player.id, "chars"):
        await _deny(message)
        return
    if not message.reply_to_message or not message.reply_to_message.photo:
        await send_text(message, "Reply to a photo with /addchar Name | Series | Rarity | alias.", ephemeral=True)
        return
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) < 2:
        await send_text(message, "Add Name | Series | Rarity after the command.", ephemeral=True)
        return
    bits = [bit.strip() for bit in payload[1].split("|")]
    if len(bits) < 3:
        await send_text(message, "Need Name | Series | Rarity.", ephemeral=True)
        return
    rarity = rarity_from_text(bits[2])
    if rarity is None:
        await send_text(message, "Unknown rarity.", ephemeral=True)
        return
    key = normalize_name(bits[0])
    if not key:
        await send_text(message, "Name is empty.", ephemeral=True)
        return
    if await session.scalar(select(Character).where(Character.name_key == key)):
        await send_text(message, "That name already exists.", ephemeral=True)
        return
    character = Character(name=bits[0][:128], name_key=key, series=bits[1][:128], rarity=rarity.key, catch_count=0)
    session.add(character)
    await session.flush()
    dest = settings.data_dir / "uploads" / f"{character.id}.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    await message.bot.download(message.reply_to_message.photo[-1], destination=dest)
    character.custom_path = str(dest)
    if len(bits) > 3 and normalize_name(bits[3]):
        session.add(Alias(name_key=normalize_name(bits[3]), character_id=character.id))
    await send_text(message, f"Added {h(character.name)} as #{character.id}.")


@router.message(Command("updatechar", "update"))
async def updatechar_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not await has_power(session, settings, player.id, "chars"):
        await _deny(message)
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await send_text(message, "Use /updatechar &lt;id&gt; Name | Series | Rarity.", ephemeral=True)
        return
    character = await session.get(Character, int(parts[1]))
    if character is None:
        await send_text(message, "Unknown character.", ephemeral=True)
        return
    if len(parts) > 2:
        bits = [bit.strip() for bit in parts[2].split("|")]
        if bits and bits[0]:
            character.name = bits[0][:128]
            character.name_key = normalize_name(bits[0])
        if len(bits) > 1 and bits[1]:
            character.series = bits[1][:128]
        if len(bits) > 2:
            rarity = rarity_from_text(bits[2])
            if rarity:
                character.rarity = rarity.key
    if message.reply_to_message and message.reply_to_message.photo:
        dest = settings.data_dir / "uploads" / f"{character.id}.jpg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        await message.bot.download(message.reply_to_message.photo[-1], destination=dest)
        character.custom_path = str(dest)
    await send_text(message, f"Updated #{character.id} {h(character.name)}.")


@router.message(Command("delete", "remove"))
async def delete_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not await has_power(session, settings, player.id, "chars"):
        await _deny(message)
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await send_text(message, "Use /delete &lt;card id&gt;.", ephemeral=True)
        return
    card = await session.get(Card, int(parts[1]))
    if card is None:
        await send_text(message, "No such card.", ephemeral=True)
        return
    await session.delete(card)
    await send_text(message, f"Deleted card #{parts[1]}.")


@router.message(Command("givemoney"))
async def givemoney_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not await has_power(session, settings, player.id, "economy"):
        await _deny(message)
        return
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].lstrip("-").isdigit():
        await send_text(message, "Use /givemoney &lt;user id&gt; &lt;amount&gt;.", ephemeral=True)
        return
    target = await session.get(User, int(parts[1]))
    if target is None:
        await send_text(message, "Unknown user.", ephemeral=True)
        return
    await adjust_balance(session, target, int(parts[2]))
    await send_text(message, f"Balance for {target.id} is now {target.balance}.", ephemeral=True)


@router.message(Command("rmmoney"))
async def rmmoney_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not await has_power(session, settings, player.id, "economy"):
        await _deny(message)
        return
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await send_text(message, "Use /rmmoney &lt;user id&gt; &lt;amount&gt;.", ephemeral=True)
        return
    target = await session.get(User, int(parts[1]))
    if target is None:
        await send_text(message, "Unknown user.", ephemeral=True)
        return
    await adjust_balance(session, target, -int(parts[2]))
    await send_text(message, f"Balance for {target.id} is now {target.balance}.", ephemeral=True)


@router.message(Command("gencode", "gen"))
async def gencode_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await _deny(message)
        return
    parts = (message.text or "").split()
    coins = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    uses = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
    character_id = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
    code = await create_code(session, coins, character_id, uses)
    await send_text(
        message,
        f"Code <code>{h(code.code)}</code> · coins {code.coins} · uses {code.uses_left}.",
        copy_keyboard(settings, code.code),
        ephemeral=True,
    )


@router.message(Command("redeem"))
async def redeem_cmd(message: Message, session: AsyncSession, player: User) -> None:
    from ..repo import redeem

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await send_text(message, "Use /redeem &lt;code&gt;.", ephemeral=True)
        return
    status, note = await redeem(session, player, parts[1])
    await send_text(message, f"Redeem {h(status)}. {h(note)}", ephemeral=True)


@router.message(Command("backup"))
async def backup_cmd(message: Message, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await _deny(message)
        return
    from ..backup import run_backup

    path = await run_backup(settings)
    if path is None:
        await send_text(message, "Backup failed or database is empty.", ephemeral=True)
        return
    await send_text(message, f"Backup saved: <code>{h(path.name)}</code>", ephemeral=True)
    await audit(message.bot, settings, "Backup manual", path.name)


@router.message(Command("savegroup", "reggroup"))
async def savegroup_cmd(message: Message, session: AsyncSession, settings: Settings) -> None:
    if message.chat.type == "private":
        await send_text(message, "Use this inside a group.", ephemeral=True)
        return
    await ensure_group(session, message.chat.id, message.chat.title or "", settings)
    await send_text(message, "This group will spawn characters.")
    await audit(message.bot, settings, "Group saved", f"{message.chat.title} · {message.chat.id}")


@router.message(Command("broadcast"))
async def broadcast_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await _deny(message)
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await send_text(message, "Use /broadcast &lt;text&gt;.", ephemeral=True)
        return
    text = parts[1]
    user_ids = (await session.scalars(select(User.id).where(User.banned.is_(False)))).all()
    group_ids = (await session.scalars(select(Group.chat_id))).all()
    sent = 0
    for chat_id in list(dict.fromkeys([*user_ids, *group_ids]))[:400]:
        try:
            await message.bot.send_message(chat_id, text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            continue
    await send_text(message, f"Broadcast delivered to {sent} chats.", ephemeral=True)


@router.message(Command("removeall"))
async def removeall_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await _deny(message)
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await send_text(message, "Use /removeall &lt;user id&gt; and confirm the button.", ephemeral=True)
        return
    await send_text(
        message,
        f"Delete every card owned by {parts[1]}?",
        confirm_keyboard(settings, f"op:rmall:{parts[1]}"),
        ephemeral=True,
    )


@router.callback_query(F.data.startswith("op:rmall:"))
async def removeall_cb(callback: CallbackQuery, session: AsyncSession, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await callback.answer("Owner only", show_alert=True)
        return
    user_id = int(callback.data.split(":")[2])
    count = await clear_user_cards(session, user_id)
    await edit_panel(callback, f"Removed {count} cards from {user_id}.")


@router.message(Command("transfer"))
async def transfer_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await _deny(message)
        return
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await send_text(message, "Use /transfer &lt;card id&gt; &lt;user id&gt;.", ephemeral=True)
        return
    card = await session.get(Card, int(parts[1]))
    target = await session.get(User, int(parts[2]))
    if card is None or target is None:
        await send_text(message, "Card or user is missing.", ephemeral=True)
        return
    card.user_id = target.id
    card.locked = False
    card.source = "transfer"
    await send_text(message, f"Card #{card.id} now belongs to {target.id}.")


@router.message(Command("owner", "panel"))
async def owner_cmd(message: Message, player: User, settings: Settings, state: FSMContext) -> None:
    if not settings.is_owner(player.id):
        await _deny(message)
        return
    if message.chat.type != "private":
        await send_text(message, "Open the panel in a private chat.", ephemeral=True)
        return
    if settings.owner_password:
        await state.set_state(Panel.wait_password)
        await send_text(message, "Send the panel password. This message stays in the chat only until you reply.")
        return
    await send_text(message, "<b>Owner panel</b>", owner_keyboard(settings))


@router.message(StateFilter(Panel.wait_password), F.text)
async def owner_password(message: Message, player: User, settings: Settings, state: FSMContext) -> None:
    if not settings.is_owner(player.id) or message.chat.type != "private":
        await state.clear()
        return
    supplied = message.text or ""
    try:
        await message.delete()
    except Exception:
        pass
    if not hmac.compare_digest(supplied, settings.owner_password):
        await state.clear()
        await send_text(message, "Wrong password.")
        return
    await state.clear()
    await send_text(message, "<b>Owner panel</b>", owner_keyboard(settings))


@router.callback_query(F.data == "op:counts")
async def counts_cb(callback: CallbackQuery, session: AsyncSession, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await callback.answer("Owner only", show_alert=True)
        return
    users, characters, groups = await global_counts(session)
    await edit_panel(callback, f"Players {users}\nCharacters {characters}\nGroups {groups}", owner_keyboard(settings))


@router.callback_query(F.data == "op:restart")
async def restart_cb(callback: CallbackQuery, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await callback.answer("Owner only", show_alert=True)
        return
    await edit_panel(callback, "Restart the process?", confirm_keyboard(settings, "op:restart:yes", "op:counts"))


@router.callback_query(F.data == "op:restart:yes")
async def restart_now(callback: CallbackQuery, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await callback.answer("Owner only", show_alert=True)
        return
    await callback.answer("Restarting")
    os._exit(0)


@router.message(Command("restart"))
async def restart_cmd(message: Message, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await _deny(message)
        return
    await send_text(message, "Restarting.")
    os._exit(0)
