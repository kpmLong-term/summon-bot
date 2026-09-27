"""Catch loop, album, profile, dailies, and quests."""

from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..bridge import KurigramBridge
from ..config import Settings
from ..copy_text import HELP_HOME, HELP_PLAY, HELP_STAFF, HELP_TRADE, home_text
from ..db import Character, Group, Spawn, User
from ..fonts import apply_font
from ..game import RARITY_BY_KEY, format_duration, now_ts
from ..keyboards import (
    collection_keyboard,
    font_keyboard,
    help_keyboard,
    hint_keyboard,
    hmode_keyboard,
    private_menu,
    quest_keyboard,
    start_keyboard,
    top_keyboard,
)
from ..repo import (
    buy_hint,
    card_count,
    choose_character,
    claim_daily,
    claim_quest,
    collection_count,
    collection_slice,
    ensure_group,
    find_character_by_guess,
    global_counts,
    leaderboard,
    mark_spin,
    note_group_message,
    open_spawn,
    premium_active,
    search_characters,
    sync_achievements,
    track_group_member,
    try_claim,
)
from ..audit import audit
from ..telegram_ui import edit_panel, h, react, send_cached_photo, send_rich, send_text

log = logging.getLogger(__name__)
router = Router(name="play")
_CHAT_LOCKS: dict[int, asyncio.Lock] = {}

HELP_PAGES = {
    "play": HELP_PLAY,
    "trade": HELP_TRADE,
    "staff": HELP_STAFF,
}


def _lock(chat_id: int) -> asyncio.Lock:
    return _CHAT_LOCKS.setdefault(chat_id, asyncio.Lock())


def _display(player: User, name: str) -> str:
    styled = apply_font(name, player.font)
    if player.glow:
        return f"✨ {styled}"
    return styled


async def _spawn_art(character: Character, settings: Settings, kind: str):
    if character.custom_path and kind == "spawn":
        return character.custom_path
    return settings.data_dir / "art" / f"{character.id}_{kind}.png"


@router.message(CommandStart())
async def start_cmd(message: Message, player: User, settings: Settings) -> None:
    text = home_text(h(player.first_name or "collector"))
    markup = start_keyboard(settings, private=message.chat.type == "private")
    sent = await send_rich(message, text, markup, ephemeral=message.chat.type != "private")
    if sent is None:
        await send_text(message, text, markup, ephemeral=True, effect_id="5046509860389126442")
    if message.chat.type == "private":
        menu = private_menu(settings)
        if menu:
            await message.answer("Album button is under the field.", reply_markup=menu)
    await audit(
        message.bot,
        settings,
        "Start",
        f"{player.id} · @{player.username}" if player.username else f"{player.id} · {player.first_name}",
    )


@router.message(Command("help", "menu", "commands"))
async def help_cmd(message: Message, settings: Settings) -> None:
    await send_rich(message, HELP_HOME, help_keyboard(settings), ephemeral=True)


@router.message(Command("ping"))
async def ping_cmd(message: Message) -> None:
    import time

    start = time.perf_counter()
    probe = await message.answer("…")
    ms = int((time.perf_counter() - start) * 1000)
    await probe.edit_text(f"Pong. {ms} ms")


@router.message(Command("balance", "bal"))
async def balance_cmd(message: Message, player: User) -> None:
    premium = "Premium is active." if premium_active(player) else "No premium."
    await send_text(
        message,
        f"<b>Balance</b>\n{player.balance} coins\n{premium}",
        ephemeral=True,
    )


@router.message(Command("daily"))
async def daily_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    status, payout, extra = await claim_daily(session, player, settings.daily_reward)
    if status == "wait":
        await send_text(message, f"Daily is ready in {format_duration(extra)}.", ephemeral=True)
        return
    await send_text(
        message,
        f"Daily claimed. <b>+{payout}</b> coins. Streak {extra}. Balance {player.balance}.",
        ephemeral=True,
        effect_id="5046509860389126442",
    )


@router.message(Command("spin"))
async def spin_cmd(message: Message, session: AsyncSession, player: User) -> None:
    from ..game import spin_reward

    if player.last_spin and now_ts() - player.last_spin < 24 * 60 * 60:
        wait = player.last_spin + 24 * 60 * 60 - now_ts()
        await send_text(message, f"Spin is ready in {format_duration(wait)}.", ephemeral=True)
        return
    dice = await message.answer_dice(emoji="🎲")
    reward, lucky = spin_reward(dice.dice.value if dice.dice else 1)
    status = await mark_spin(session, player, reward)
    if status != "ok":
        return
    note = " Lucky six." if lucky else ""
    await send_text(message, f"Spin rolled {dice.dice.value}. <b>+{reward}</b> coins.{note}", ephemeral=True)


@router.message(Command("streak"))
async def streak_cmd(message: Message, player: User) -> None:
    await send_text(
        message,
        f"Current streak {player.streak}. Best {player.best_streak}.",
        ephemeral=True,
    )


@router.message(Command("achievements", "ach", "badges"))
async def achievements_cmd(message: Message, session: AsyncSession, player: User) -> None:
    from ..db import Achievement
    from ..game import ACHIEVEMENTS

    await sync_achievements(session, player)
    have = set((await session.scalars(select(Achievement.key).where(Achievement.user_id == player.id))).all())
    lines = ["<b>Achievements</b>"]
    for key, label in ACHIEVEMENTS:
        mark = "✅" if key in have else "▫️"
        lines.append(f"{mark} {label}")
    await send_text(message, "\n".join(lines), ephemeral=True)


@router.message(Command("quests"))
async def quests_cmd(message: Message, player: User, settings: Settings) -> None:
    from ..repo import roll_quest_day

    roll_quest_day(player)
    text = (
        "<b>Today</b>\n"
        f"Catches {player.quest_catch}/1\n"
        f"Group messages {player.quest_msgs}/15\n"
        "Daily claim is the third box.\n"
        "Rewards are claimed with the buttons."
    )
    await send_rich(message, text, quest_keyboard(settings), ephemeral=True)


@router.callback_query(F.data.startswith("quest:"))
async def quest_cb(callback: CallbackQuery, session: AsyncSession, player: User) -> None:
    key = callback.data.split(":", 1)[1]
    status, reward = await claim_quest(session, player, key)
    if status == "ok":
        await callback.answer(f"+{reward} coins", show_alert=True)
    elif status == "used":
        await callback.answer("Already claimed today", show_alert=True)
    else:
        await callback.answer("Not finished yet", show_alert=True)


@router.message(Command("profile"))
async def profile_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    count = await card_count(session, player.id)
    premium = "yes" if premium_active(player) else "no"
    fav = ""
    if player.favorite_card_id:
        fav = f"\nFavorite card #{player.favorite_card_id}"
    caption = (
        f"<b>{h(player.first_name)}</b>\n"
        f"Cards {count}\nCoins {player.balance}\nClaims {player.claims}\n"
        f"Streak {player.streak}\nPremium {premium}{fav}"
    )
    if player.favorite_card_id:
        from ..db import Card

        card = await session.get(Card, player.favorite_card_id)
        if card and card.user_id == player.id:
            character = await session.get(Character, card.character_id)
            if character:
                path = await _spawn_art(character, settings, "card")
                await send_cached_photo(
                    message.bot,
                    session,
                    message.chat.id,
                    f"card:{character.id}",
                    path,
                    caption,
                    receiver_user_id=None if message.chat.type == "private" else message.from_user.id,
                )
                return
    await send_text(message, caption, ephemeral=True)


@router.message(Command("collection", "harem"))
async def collection_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    target = player
    if message.reply_to_message and message.reply_to_message.from_user:
        other = await session.get(User, message.reply_to_message.from_user.id)
        if other:
            target = other
    await _send_collection(message, session, settings, target, player, 0)


async def _send_collection(message: Message, session: AsyncSession, settings: Settings, target: User, viewer: User, page: int) -> None:
    mode = target.hmode if target.id == viewer.id else "all"
    total = await collection_count(session, target.id, mode)
    if total <= 0:
        await send_text(message, "No cards in this view yet.", ephemeral=True)
        return
    page = max(0, min(page, total - 1))
    row = await collection_slice(session, target.id, mode, page)
    if row is None:
        await send_text(message, "That page is empty.", ephemeral=True)
        return
    card, character = row
    rarity = RARITY_BY_KEY.get(character.rarity)
    label = rarity.label if rarity else character.rarity
    caption = (
        f"<b>{h(_display(viewer, character.name))}</b>\n"
        f"{h(label)} · {h(character.series)}\n"
        f"Card #{card.id} · {page + 1}/{total}"
    )
    path = await _spawn_art(character, settings, "card")
    markup = collection_keyboard(settings, target.id, page, total)
    kwargs = {}
    if message.chat.type != "private":
        kwargs["receiver_user_id"] = viewer.id
    await send_cached_photo(
        message.bot,
        session,
        message.chat.id,
        f"card:{character.id}",
        path,
        caption,
        markup,
        **kwargs,
    )


@router.callback_query(F.data.startswith("col:"))
async def collection_cb(callback: CallbackQuery, session: AsyncSession, player: User, settings: Settings) -> None:
    parts = callback.data.split(":")
    if len(parts) == 2:
        owner_id, page = player.id, int(parts[1])
    else:
        owner_id, page = int(parts[1]), int(parts[2])
    target = await session.get(User, owner_id)
    if target is None or callback.message is None:
        await callback.answer("Missing album")
        return
    mode = target.hmode if target.id == player.id else "all"
    total = await collection_count(session, target.id, mode)
    if total <= 0:
        await callback.answer("Empty")
        return
    page = max(0, min(page, total - 1))
    row = await collection_slice(session, target.id, mode, page)
    if row is None:
        await callback.answer("Empty")
        return
    card, character = row
    rarity = RARITY_BY_KEY.get(character.rarity)
    caption = (
        f"<b>{h(_display(player, character.name))}</b>\n"
        f"{h(rarity.label if rarity else character.rarity)} · {h(character.series)}\n"
        f"Card #{card.id} · {page + 1}/{total}"
    )
    path = await _spawn_art(character, settings, "card")
    from aiogram.types import FSInputFile, InputMediaPhoto

    try:
        await callback.message.edit_media(
            InputMediaPhoto(media=FSInputFile(str(path)), caption=caption[:1024]),
            reply_markup=collection_keyboard(settings, target.id, page, total),
        )
    except Exception:
        log.exception("collection edit failed")
    await callback.answer()


@router.callback_query(F.data.startswith("fav:"))
async def fav_cb(callback: CallbackQuery, session: AsyncSession, player: User) -> None:
    _, owner_raw, page_raw = callback.data.split(":")
    if int(owner_raw) != player.id:
        await callback.answer("Only the owner can favorite this album", show_alert=True)
        return
    row = await collection_slice(session, player.id, player.hmode, int(page_raw))
    if row is None:
        await callback.answer("Nothing here")
        return
    player.favorite_card_id = row[0].id
    await callback.answer(f"Favorite set to #{row[0].id}")


@router.message(Command("fav"))
async def fav_cmd(message: Message, session: AsyncSession, player: User) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        await send_text(message, "Use /fav &lt;card id&gt; or the button inside /collection.", ephemeral=True)
        return
    from ..db import Card

    card = await session.get(Card, int(parts[1]))
    if card is None or card.user_id != player.id:
        await send_text(message, "That card is not yours.", ephemeral=True)
        return
    player.favorite_card_id = card.id
    await send_text(message, f"Favorite is now #{card.id}.", ephemeral=True)


@router.message(Command("hmode"))
async def hmode_cmd(message: Message, settings: Settings, player: User) -> None:
    await send_text(
        message,
        f"Album filter is <b>{h(player.hmode)}</b>.",
        hmode_keyboard(settings),
        ephemeral=True,
    )


@router.callback_query(F.data.startswith("hmode:"))
async def hmode_cb(callback: CallbackQuery, player: User) -> None:
    player.hmode = callback.data.split(":", 1)[1]
    await callback.answer(f"Filter {player.hmode}")


@router.message(Command("font", "style"))
async def font_cmd(message: Message, settings: Settings, player: User) -> None:
    sample = apply_font("Summon", player.font)
    await send_text(message, f"Font <b>{h(player.font)}</b>\n{h(sample)}", font_keyboard(settings), ephemeral=True)


@router.callback_query(F.data.startswith("font:"))
async def font_cb(callback: CallbackQuery, player: User) -> None:
    player.font = callback.data.split(":", 1)[1]
    await callback.answer("Font saved")


@router.message(Command("check", "info"))
async def check_cmd(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await send_text(message, "Use /check &lt;name or card id&gt;.", ephemeral=True)
        return
    query = parts[1].strip()
    if query.isdigit():
        from ..db import Card

        card = await session.get(Card, int(query))
        if card is None:
            await send_text(message, "No card with that id.", ephemeral=True)
            return
        character = await session.get(Character, card.character_id)
        owner = await session.get(User, card.user_id)
        if character is None:
            return
        rarity = RARITY_BY_KEY.get(character.rarity)
        await send_text(
            message,
            (
                f"<b>{h(character.name)}</b> #{card.id}\n"
                f"{h(rarity.label if rarity else character.rarity)} · {h(character.series)}\n"
                f"Owner {h(owner.first_name if owner else card.user_id)}\n"
                f"Caught {character.catch_count} times · source {h(card.source)}"
            ),
            ephemeral=True,
        )
        return
    character = await find_character_by_guess(session, query)
    if character is None:
        found = await search_characters(session, query, limit=5)
        if not found:
            await send_text(message, "No character matched.", ephemeral=True)
            return
        lines = ["Closest names:"] + [f"• {h(item.name)} ({h(item.rarity)})" for item in found]
        await send_text(message, "\n".join(lines), ephemeral=True)
        return
    rarity = RARITY_BY_KEY.get(character.rarity)
    await send_text(
        message,
        f"<b>{h(character.name)}</b>\n{h(rarity.label if rarity else character.rarity)} · {h(character.series)}\nCaught {character.catch_count} times.",
        ephemeral=True,
    )


@router.message(Command("search", "find"))
async def search_cmd(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await send_text(message, "Use /search &lt;name&gt;.", ephemeral=True)
        return
    rows = await search_characters(session, parts[1], limit=12)
    if not rows:
        await send_text(message, "Nothing matched.", ephemeral=True)
        return
    lines = [f"• {h(row.name)} — {h(RARITY_BY_KEY[row.rarity].label)}" for row in rows if row.rarity in RARITY_BY_KEY]
    await send_text(message, "<b>Search</b>\n" + "\n".join(lines), ephemeral=True)


@router.message(Command("claimlist"))
async def claimlist_cmd(message: Message, session: AsyncSession) -> None:
    spawn = await session.get(Spawn, message.chat.id)
    if spawn is None or spawn.expires_at <= now_ts():
        await send_text(message, "Nothing is waiting in this chat.", ephemeral=True)
        return
    left = spawn.expires_at - now_ts()
    await send_text(message, f"A character is still up for {format_duration(left)}.", ephemeral=True)


@router.message(Command("stats", "server"))
async def stats_cmd(message: Message, session: AsyncSession, settings: Settings, bridge: KurigramBridge, player: User) -> None:
    users, characters, groups = await global_counts(session)
    group = await session.get(Group, message.chat.id)
    progress = ""
    if group:
        progress = f"\nThis chat {group.message_count}/{group.spawn_every} toward the next spawn."
    members = ""
    if message.chat.type != "private":
        count = await bridge.member_count(message.chat.id)
        if count:
            members = f"\nKurigram member count {count}."
    mine = await card_count(session, player.id)
    await send_text(
        message,
        f"<b>Stats</b>\nPlayers {users}\nCharacters {characters}\nGroups {groups}\nYour cards {mine}{progress}{members}",
        ephemeral=True,
    )


@router.message(Command("top", "rank"))
async def top_cmd(message: Message, session: AsyncSession, settings: Settings) -> None:
    await send_text(message, await _top_text(session, "cards"), top_keyboard(settings), ephemeral=True)


async def _top_text(session: AsyncSession, kind: str) -> str:
    rows = await leaderboard(session, kind)
    title = "Top albums" if kind == "cards" else "Top purses"
    if not rows:
        return f"<b>{title}</b>\nNo one yet."
    lines = [f"<b>{title}</b>"]
    for index, user in enumerate(rows, start=1):
        if kind == "coins":
            lines.append(f"{index}. {h(user.first_name)} — {user.balance}")
        else:
            lines.append(f"{index}. {h(user.first_name)}")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("top:"))
async def top_cb(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    kind = callback.data.split(":", 1)[1]
    await edit_panel(callback, await _top_text(session, kind), top_keyboard(settings))


@router.callback_query(F.data == "go:home")
async def home_cb(callback: CallbackQuery, player: User, settings: Settings) -> None:
    text = home_text(h(player.first_name or "collector"))
    await edit_panel(callback, text, start_keyboard(settings, private=True))


@router.callback_query(F.data == "go:help")
async def help_cb_open(callback: CallbackQuery, settings: Settings) -> None:
    await edit_panel(callback, HELP_HOME, help_keyboard(settings))


@router.callback_query(F.data.startswith("help:"))
async def help_page_cb(callback: CallbackQuery, settings: Settings) -> None:
    page = callback.data.split(":", 1)[1]
    await edit_panel(callback, HELP_PAGES.get(page, HELP_HOME), help_keyboard(settings))


@router.callback_query(F.data == "go:daily")
async def daily_cb(callback: CallbackQuery, session: AsyncSession, player: User, settings: Settings) -> None:
    status, payout, extra = await claim_daily(session, player, settings.daily_reward)
    if status == "wait":
        await callback.answer(f"Ready in {format_duration(extra)}", show_alert=True)
        return
    await callback.answer(f"+{payout} · streak {extra}", show_alert=True)


@router.callback_query(F.data == "go:quests")
async def quests_cb(callback: CallbackQuery, player: User, settings: Settings) -> None:
    from ..repo import roll_quest_day

    roll_quest_day(player)
    text = f"<b>Today</b>\nCatches {player.quest_catch}/1\nMessages {player.quest_msgs}/15"
    await edit_panel(callback, text, quest_keyboard(settings))


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def group_text(message: Message, session: AsyncSession, player: User | None, settings: Settings, state: FSMContext) -> None:
    if player is None or not message.text or message.text.startswith("/"):
        return
    if await state.get_state():
        return
    if message.from_user:
        await track_group_member(session, message.chat.id, message.from_user)
    async with _lock(message.chat.id):
        group = await ensure_group(session, message.chat.id, message.chat.title or "", settings)
        claimed = await try_claim(session, message.chat.id, player, message.text)
        if claimed.ok and claimed.character is not None:
            rarity = RARITY_BY_KEY[claimed.character.rarity]
            fresh = ""
            if claimed.new_achievements:
                fresh = "\nNew achievement unlocked."
            await send_text(
                message,
                (
                    f"<b>{h(message.from_user.full_name)}</b> caught "
                    f"<b>{h(_display(player, claimed.character.name))}</b> "
                    f"({h(rarity.label)}) · card #{claimed.card_id}.{fresh}"
                ),
                reply_to=message.message_id,
                effect_id="5104841245755180586",
            )
            await react(message.bot, message.chat.id, message.message_id)
            if rarity.key in {"mythic", "limited", "celestial"}:
                try:
                    await message.bot.set_chat_member_tag(message.chat.id, player.id, tag=rarity.label.split()[0][:16])
                except Exception:
                    pass
            return
        should = await note_group_message(session, group, player)
        if not should:
            return
        character = await choose_character(session, message.chat.id)
        if character is None:
            return
        path = await _spawn_art(character, settings, "spawn")
        rarity = RARITY_BY_KEY[character.rarity]
        try:
            sent = await send_cached_photo(
                message.bot,
                session,
                message.chat.id,
                f"spawnc:{character.id}" if character.custom_path else f"spawn:{character.id}",
                path,
                f"{rarity.emoji} Someone appeared. Type their name. You have {settings.spawn_seconds}s.",
                hint_keyboard(settings, message.chat.id),
            )
        except Exception:
            log.exception("spawn send failed")
            return
        await open_spawn(session, message.chat.id, character.id, sent.message_id, settings.spawn_seconds)


@router.callback_query(F.data.startswith("hint:"))
async def hint_cb(callback: CallbackQuery, session: AsyncSession, player: User, settings: Settings) -> None:
    chat_id = int(callback.data.split(":", 1)[1])
    if callback.message and callback.message.chat.id != chat_id:
        await callback.answer()
        return
    status, text = await buy_hint(session, chat_id, player, settings.hint_price)
    if status == "funds":
        await callback.answer("Not enough coins", show_alert=True)
        return
    if status == "none":
        await callback.answer("That spawn is over", show_alert=True)
        return
    await callback.answer(text[:180], show_alert=True)
