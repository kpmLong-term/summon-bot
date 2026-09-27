"""Reference Summon-bot commands not covered elsewhere."""

from __future__ import annotations

import random

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import Card, Character, User, UserInventory
from ..game import RARITY_BY_KEY, format_duration, now_ts
from ..keyboards import _btn
from ..repo import card_count, has_power, premium_active
from ..repo_extras import (
    buy_from_pool,
    cancel_auction,
    claim_list_text,
    cooldown_left,
    grant_item,
    hclaim,
    hstats_payload,
    inventory_text,
    list_open_auctions,
    market_pool_rows,
    my_bids,
    refresh_market_pool,
    remove_user_character,
    sell_to_pool_back,
    set_claim_chance,
    set_cooldown,
)
from ..telegram_ui import edit_panel, h, send_text

router = Router(name="extras")


def _cshop_keyboard(settings: Settings, characters: list[Character], player: User):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    for character in characters:
        from ..game import shop_price

        price = int(shop_price(character.rarity, premium_active(player)) * 1.2)
        rarity = RARITY_BY_KEY.get(character.rarity)
        label = (character.name[:18], f"cshop:buy:{character.id}:{price}")
        rows.append([_btn(settings, f"Buy {character.name[:14]} ({price})", callback=f"cshop:buy:{character.id}")])
    rows.append([_btn(settings, f"Refresh ({settings.market_refresh_price})", callback="cshop:refresh", style="primary")])
    rows.append([_btn(settings, "Sell menu", callback="cshop:sell", style="success")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _cshop_text(session: AsyncSession, settings: Settings, player: User) -> tuple[str, list[Character]]:
    characters = await market_pool_rows(session, settings)
    lines = [f"<b>Market pool</b>\nBalance {player.balance} coins\n"]
    for character in characters:
        from ..game import shop_price

        price = int(shop_price(character.rarity, premium_active(player)) * 1.2)
        rarity = RARITY_BY_KEY.get(character.rarity)
        lines.append(f"• {h(character.name)} — {h(rarity.label if rarity else character.rarity)} — {price}")
    return "\n".join(lines), characters


@router.message(Command("claimlist"))
async def claimlist_cmd(message: Message, session: AsyncSession) -> None:
    await send_text(message, await claim_list_text(session), ephemeral=True)


@router.message(Command("setclaim"))
async def setclaim_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await send_text(message, "Owner only.", ephemeral=True)
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await send_text(
            message,
            "Use /setclaim &lt;rarity_id&gt; &lt;weight&gt;. Example: /setclaim 5 0.4. Set 0 to turn an edition off.",
            ephemeral=True,
        )
        return
    try:
        rarity_id = int(parts[1])
        chance = float(parts[2])
    except ValueError:
        await send_text(message, "Numbers only.", ephemeral=True)
        return
    if rarity_id < 1 or rarity_id > len(RARITY_BY_KEY):
        await send_text(message, f"Rarity id must be 1–{len(RARITY_BY_KEY)}.", ephemeral=True)
        return
    status = await set_claim_chance(session, rarity_id, chance)
    await send_text(message, "Updated." if status == "ok" else "Unknown id.", ephemeral=True)


@router.message(Command("hclaim", "claim"))
async def hclaim_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if settings.official_group_id and message.chat.id != settings.official_group_id:
        await send_text(message, "Use the official group for /hclaim, or leave OFFICIAL_GROUP_ID empty.", ephemeral=True)
        return
    status, character, card = await hclaim(session, player, settings)
    if status.startswith("wait:"):
        wait = int(status.split(":")[1])
        await send_text(message, f"Hclaim limit reached. Try again in {format_duration(wait)}.", ephemeral=True)
        return
    if status == "off":
        await send_text(message, "All hclaim editions are off. Owner can use /setclaim.", ephemeral=True)
        return
    if status == "empty" or character is None or card is None:
        await send_text(message, "No characters in the database yet.", ephemeral=True)
        return
    rarity = RARITY_BY_KEY.get(character.rarity)
    await send_text(
        message,
        f"<b>Hclaim</b>\nYou received <b>{h(character.name)}</b> ({h(rarity.label if rarity else character.rarity)}) · card #{card.id}.",
    )


@router.message(Command("cshop000000"))
async def cshop_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    text, characters = await _cshop_text(session, settings, player)
    await send_text(message, text, _cshop_keyboard(settings, characters, player), ephemeral=True)


@router.callback_query(F.data == "cshop:refresh")
async def cshop_refresh(callback: CallbackQuery, session: AsyncSession, player: User, settings: Settings) -> None:
    if player.balance < settings.market_refresh_price:
        await callback.answer("Not enough coins", show_alert=True)
        return
    player.balance -= settings.market_refresh_price
    await refresh_market_pool(session, settings)
    text, characters = await _cshop_text(session, settings, player)
    await edit_panel(callback, text, _cshop_keyboard(settings, characters, player))


@router.callback_query(F.data.startswith("cshop:buy:"))
async def cshop_buy(callback: CallbackQuery, session: AsyncSession, player: User, settings: Settings) -> None:
    character_id = int(callback.data.split(":")[2])
    status, card = await buy_from_pool(session, player, character_id)
    if status != "ok":
        await callback.answer({"funds": "Not enough coins", "gone": "Sold out"}.get(status, status), show_alert=True)
        return
    await callback.answer(f"Card #{card.id}" if card else "Bought")
    text, characters = await _cshop_text(session, settings, player)
    await edit_panel(callback, text, _cshop_keyboard(settings, characters, player))


@router.callback_query(F.data == "cshop:sell")
async def cshop_sell_menu(callback: CallbackQuery, session: AsyncSession, player: User, settings: Settings) -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows = (
        await session.execute(
            select(Card, Character)
            .join(Character, Character.id == Card.character_id)
            .where(Card.user_id == player.id, Card.locked.is_(False))
            .order_by(Card.id.desc())
            .limit(12)
        )
    ).all()
    if not rows:
        await callback.answer("Nothing to sell", show_alert=True)
        return
    buttons = [
        [_btn(settings, f"Sell #{card.id}", callback=f"cshop:sell:{card.id}")]
        for card, _character in rows
    ]
    await edit_panel(callback, "<b>Sell to market</b>\nPick a card.", InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("cshop:sell:"))
async def cshop_sell_do(callback: CallbackQuery, session: AsyncSession, player: User, settings: Settings) -> None:
    card_id = int(callback.data.split(":")[2])
    status, payout = await sell_to_pool_back(session, player, card_id, settings)
    if status != "ok":
        await callback.answer("Could not sell", show_alert=True)
        return
    await callback.answer(f"+{payout} coins")
    text, characters = await _cshop_text(session, settings, player)
    await edit_panel(callback, text, _cshop_keyboard(settings, characters, player))


@router.message(Command("inv", "inventory"))
async def inv_cmd(message: Message, session: AsyncSession, player: User) -> None:
    cards = await card_count(session, player.id)
    text = await inventory_text(session, player.id)
    await send_text(message, f"{text}\n\nCards owned: {cards}.", ephemeral=True)


@router.message(Command("hstats", "me"))
async def hstats_cmd(message: Message, session: AsyncSession, player: User | None) -> None:
    target_id = player.id if player else message.from_user.id
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    payload = await hstats_payload(session, target_id)
    if payload is None:
        await send_text(message, "Player not found.", ephemeral=True)
        return
    user = payload["user"]
    lines = [
        f"<b>{h(user.first_name)}</b>",
        f"Cards {payload['total']} · unique rarities {payload['unique']} · rank #{payload['rank']}",
        f"Coins {user.balance} · catches {user.claims} · streak {user.streak}",
    ]
    for rarity_key, count in payload["rows"]:
        rarity = RARITY_BY_KEY.get(rarity_key)
        lines.append(f"{rarity.emoji if rarity else '•'} {count}")
    await send_text(message, "\n".join(lines), ephemeral=True)


@router.message(Command("auctionlist", "auction_list"))
async def auctionlist_cmd(message: Message, session: AsyncSession) -> None:
    rows = await list_open_auctions(session)
    if not rows:
        await send_text(message, "No open auctions.", ephemeral=True)
        return
    lines = ["<b>Open auctions</b>"]
    for auction, card, character in rows:
        left = format_duration(auction.ends_at - now_ts())
        lines.append(
            f"#{auction.id} · {h(character.name)} · bid {auction.current_bid or auction.start_price} · {left} · card {card.id}"
        )
    await send_text(message, "\n".join(lines), ephemeral=True)


@router.message(Command("mybids"))
async def mybids_cmd(message: Message, session: AsyncSession, player: User) -> None:
    rows = await my_bids(session, player.id)
    if not rows:
        await send_text(message, "You have no active bids.", ephemeral=True)
        return
    lines = ["<b>Your bids</b>"]
    for auction in rows:
        lines.append(f"#{auction.id} · {auction.current_bid} · ends in {format_duration(auction.ends_at - now_ts())}")
    await send_text(message, "\n".join(lines), ephemeral=True)


@router.message(Command("cancelauction"))
async def cancelauction_cmd(message: Message, session: AsyncSession, player: User) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await send_text(message, "Use /cancelauction &lt;auction id&gt;.", ephemeral=True)
        return
    status = await cancel_auction(session, player.id, int(parts[1]))
    await send_text(message, f"Result: {h(status)}.", ephemeral=True)


@router.message(Command("nguess_end"))
async def nguess_end_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not await has_power(session, settings, player.id, "moderate") and not settings.is_owner(player.id):
        await send_text(message, "Sudo only.", ephemeral=True)
        return
    from ..db import Quiz

    await session.execute(select(Quiz).where(Quiz.claimed.is_(False)))
    rows = (await session.scalars(select(Quiz).where(Quiz.claimed.is_(False)))).all()
    for row in rows:
        row.claimed = True
    await send_text(message, f"Closed {len(rows)} open quiz polls.", ephemeral=True)


@router.message(Command("pinfo"))
async def pinfo_cmd(message: Message, session: AsyncSession) -> None:
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    user = await session.get(User, target.id)
    if user is None:
        await send_text(message, "Unknown user.", ephemeral=True)
        return
    prem = premium_active(user)
    await send_text(
        message,
        f"<b>{h(target.full_name)}</b>\nPremium: {'yes' if prem else 'no'}\nUntil: {user.premium_until}",
        ephemeral=True,
    )


@router.message(Command("unpremium"))
async def unpremium_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await send_text(message, "Owner only.", ephemeral=True)
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await send_text(message, "Use /unpremium &lt;user id&gt;.", ephemeral=True)
        return
    user = await session.get(User, int(parts[1]))
    if user is None:
        await send_text(message, "Unknown user.", ephemeral=True)
        return
    user.premium_until = 0
    await send_text(message, "Premium removed.", ephemeral=True)


@router.message(Command("summon", "guess", "grab", "collect"))
async def summon_alias_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if message.chat.type == "private":
        await send_text(message, "Catch characters in a group when they spawn, or use /hclaim where enabled.", ephemeral=True)
        return
    if not await has_power(session, settings, player.id, "spawn"):
        await send_text(message, "Characters appear automatically. Sudo can use /spawn to force the next one.", ephemeral=True)
        return
    from ..repo import ensure_group

    group = await ensure_group(session, message.chat.id, message.chat.title or "", settings)
    group.message_count = group.spawn_every
    await send_text(message, "Next message will trigger a spawn.")


@router.message(Command("bomb"))
async def bomb_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    left = await cooldown_left(session, player.id, "bomb")
    if left:
        await send_text(message, f"Bomb cooldown {format_duration(left)}.", ephemeral=True)
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if target is None:
        await send_text(message, "Reply to someone with /bomb.", ephemeral=True)
        return
    if target.id == player.id:
        await send_text(message, "You cannot bomb yourself.", ephemeral=True)
        return
    bomb = (
        await session.scalars(
            select(UserInventory)
            .where(
                UserInventory.user_id == player.id,
                UserInventory.item_id == "bomb",
                UserInventory.uses_remaining > 0,
                UserInventory.expires_at > now_ts(),
            )
            .limit(1)
        )
    ).first()
    if bomb is None:
        await send_text(message, "You need a bomb item. Owner can grant via database or future shop item.", ephemeral=True)
        return
    victim_card = await session.scalar(
        select(Card).where(Card.user_id == target.id, Card.locked.is_(False)).order_by(Card.id.desc()).limit(1)
    )
    if victim_card is None:
        await send_text(message, "Target has no cards to hit.", ephemeral=True)
        return
    await session.delete(victim_card)
    bomb.uses_remaining -= 1
    await set_cooldown(session, player.id, "bomb", 24 * 3600)
    await send_text(message, f"Bomb removed one card from {h(target.full_name)}.")


@router.message(Command("steal"))
async def steal_cmd(message: Message, session: AsyncSession, player: User) -> None:
    left = await cooldown_left(session, player.id, "steal")
    if left:
        await send_text(message, f"Steal cooldown {format_duration(left)}.", ephemeral=True)
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if target is None:
        await send_text(message, "Reply with /steal.", ephemeral=True)
        return
    victim = await session.get(User, target.id)
    if victim is None or victim.balance < 100:
        await send_text(message, "Target has too few coins.", ephemeral=True)
        return
    amount = random.randint(100, min(2000, victim.balance // 2))
    victim.balance -= amount
    player.balance += amount
    await set_cooldown(session, player.id, "steal", 3600)
    await send_text(message, f"Stole {amount} coins from {h(target.full_name)}.")


@router.message(Command("skip"))
async def skip_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        await send_text(message, "Use /skip 1 to clear bomb cooldown, /skip 2 for steal, /skip 3 grants a bomb item.", ephemeral=True)
        return
    choice = parts[1]
    if choice == "1":
        await set_cooldown(session, player.id, "bomb", 0)
        await send_text(message, "Bomb cooldown cleared.", ephemeral=True)
    elif choice == "2":
        await set_cooldown(session, player.id, "steal", 0)
        await send_text(message, "Steal cooldown cleared.", ephemeral=True)
    elif choice == "3" and settings.is_owner(player.id):
        await grant_item(session, player.id, "bomb", uses=1, hours=24)
        await send_text(message, "Bomb item granted.", ephemeral=True)
    else:
        await send_text(message, "Unknown skip option.", ephemeral=True)


@router.message(Command("remove"))
async def remove_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await send_text(message, "Owner only.", ephemeral=True)
        return
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await send_text(message, "Use /remove &lt;user id&gt; &lt;character id&gt;.", ephemeral=True)
        return
    count = await remove_user_character(session, int(parts[1]), int(parts[2]))
    await send_text(message, f"Removed {count} card(s).", ephemeral=True)
