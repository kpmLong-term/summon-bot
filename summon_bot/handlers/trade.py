"""Shop, market, auctions, gifts, and the name quiz."""

from __future__ import annotations

import random

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, PollAnswer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..bridge import KurigramBridge
from ..config import Settings
from ..db import Character, User
from ..game import RARITY_BY_KEY, SHOP_RARITIES, parse_listing_price, shop_price
from ..keyboards import market_keyboard, offer_keyboard, shop_keyboard
from ..repo import (
    buy_character,
    buy_listing,
    create_listing,
    gift_card,
    market_page,
    open_auction,
    pay_coins,
    place_bid,
    premium_active,
    random_of_rarity,
    user_by_username,
)
from ..audit import audit
from ..telegram_ui import edit_panel, h, send_text

router = Router(name="trade")


async def resolve_user(message: Message, session: AsyncSession, settings: Settings, bridge: KurigramBridge, token: str) -> int | None:
    if token.isdigit():
        return int(token)
    if token.startswith("@"):
        row = await user_by_username(session, token)
        if row:
            return row.id
        try:
            chat = await message.bot.get_chat(token)
            return chat.id
        except Exception:
            return await bridge.resolve_username(token)
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    return None


@router.message(Command("shop"))
async def shop_cmd(message: Message, settings: Settings) -> None:
    await send_text(message, "<b>Shop</b>\nPick a rarity. Premium pays 10% less.", shop_keyboard(settings), ephemeral=True)


@router.callback_query(F.data == "shop:open")
async def shop_open(callback: CallbackQuery, settings: Settings) -> None:
    await edit_panel(callback, "<b>Shop</b>\nPick a rarity.", shop_keyboard(settings))


@router.callback_query(F.data.startswith("shop:r:"))
async def shop_roll(callback: CallbackQuery, session: AsyncSession, player: User, settings: Settings) -> None:
    rarity = callback.data.split(":")[2]
    if rarity not in {item.key for item in SHOP_RARITIES}:
        await callback.answer("That rarity is event-only", show_alert=True)
        return
    character = await random_of_rarity(session, rarity)
    if character is None or callback.message is None:
        await callback.answer("No characters in that rarity yet")
        return
    price = shop_price(rarity, premium_active(player))
    text = f"<b>{h(character.name)}</b>\n{h(RARITY_BY_KEY[rarity].label)}\nPrice {price} coins"
    await edit_panel(callback, text, offer_keyboard(settings, character.id, rarity))


@router.callback_query(F.data.startswith("shop:buy:"))
async def shop_buy(callback: CallbackQuery, session: AsyncSession, player: User, settings: Settings) -> None:
    character = await session.get(Character, int(callback.data.split(":")[2]))
    if character is None or character.rarity not in {item.key for item in SHOP_RARITIES}:
        await callback.answer("Unavailable", show_alert=True)
        return
    status, card = await buy_character(session, player, character)
    if status == "funds":
        await callback.answer("Not enough coins", show_alert=True)
        return
    await callback.answer(f"Card #{card.id}" if card else "Bought", show_alert=True)
    await edit_panel(
        callback,
        f"Bought <b>{h(character.name)}</b> as #{card.id}. Balance {player.balance}.",
        shop_keyboard(settings),
    )


@router.message(Command("sell", "sellchar"))
async def sell_cmd(message: Message, session: AsyncSession, player: User) -> None:
    parts = (message.text or "").split()
    if len(parts) < 3:
        await send_text(message, "Use /sell &lt;card id&gt; &lt;price&gt;.", ephemeral=True)
        return
    if not parts[1].isdigit():
        await send_text(message, "Card id must be a number.", ephemeral=True)
        return
    price = parse_listing_price(parts[2])
    if price is None:
        await send_text(message, "Price must be between 100 and 1T. k, m, and b suffixes work.", ephemeral=True)
        return
    status, listing = await create_listing(session, player, int(parts[1]), price)
    if status != "ok" or listing is None:
        await send_text(message, f"Could not list that card ({h(status)}).", ephemeral=True)
        return
    await send_text(message, f"Listed card #{listing.card_id} for {listing.price} as listing #{listing.id}.")


@router.message(Command("market"))
async def market_cmd(message: Message, session: AsyncSession, settings: Settings) -> None:
    await send_text(message, await _market_text(session, 0), market_keyboard(settings, await _ids(session, 0), 0), ephemeral=True)


async def _ids(session: AsyncSession, page: int) -> list[int]:
    rows = await market_page(session, page * 5, 5)
    return [row[0].id for row in rows]


async def _market_text(session: AsyncSession, page: int) -> str:
    rows = await market_page(session, page * 5, 5)
    if not rows:
        return "<b>Market</b>\nNo listings on this page."
    lines = ["<b>Market</b>"]
    for listing, _card, character in rows:
        rarity = RARITY_BY_KEY.get(character.rarity)
        lines.append(
            f"#{listing.id} card {listing.card_id} · {h(character.name)} · {h(rarity.label if rarity else character.rarity)} · {listing.price}"
        )
    return "\n".join(lines)


@router.callback_query(F.data.startswith("mktpage:"))
async def market_page_cb(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    page = max(0, int(callback.data.split(":")[1]))
    await edit_panel(callback, await _market_text(session, page), market_keyboard(settings, await _ids(session, page), page))


@router.callback_query(F.data.startswith("mkt:"))
async def market_buy_cb(callback: CallbackQuery, session: AsyncSession, player: User) -> None:
    status, price = await buy_listing(session, player, int(callback.data.split(":")[1]))
    messages = {
        "ok": f"Bought for {price}",
        "funds": "Not enough coins",
        "self": "That is your listing",
        "gone": "Listing is gone",
    }
    await callback.answer(messages.get(status, status), show_alert=True)


@router.message(Command("auction"))
async def auction_cmd(message: Message, session: AsyncSession, player: User) -> None:
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit():
        await send_text(message, "Use /auction &lt;card id&gt; &lt;start price&gt; [hours].", ephemeral=True)
        return
    price = parse_listing_price(parts[2])
    hours = min(72, int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 6)
    if price is None:
        await send_text(message, "Start price is too low or not a number.", ephemeral=True)
        return
    status, auction = await open_auction(session, player, int(parts[1]), price, hours)
    if status != "ok" or auction is None:
        await send_text(message, f"Could not open an auction ({h(status)}).", ephemeral=True)
        return
    await send_text(
        message,
        f"Auction #{auction.id} for card #{auction.card_id} starts at {auction.start_price}. "
        f"It closes in {hours}h.",
    )


@router.message(Command("bid"))
async def bid_cmd(message: Message, session: AsyncSession, player: User) -> None:
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit():
        await send_text(message, "Use /bid &lt;auction id&gt; &lt;amount&gt;.", ephemeral=True)
        return
    amount = parse_listing_price(parts[2])
    if amount is None:
        await send_text(message, "That bid amount is not valid.", ephemeral=True)
        return
    status = await place_bid(session, int(parts[1]), player, amount)
    await send_text(message, f"Bid result: {h(status)}.", ephemeral=True)


@router.message(Command("gift", "give"))
async def gift_cmd(message: Message, session: AsyncSession, player: User, settings: Settings, bridge: KurigramBridge, bot) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await send_text(message, "Use /gift &lt;card id&gt; by replying to someone, or /gift &lt;card id&gt; &lt;user id&gt;.", ephemeral=True)
        return
    token = parts[2] if len(parts) > 2 else ""
    if not token and message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        target_id = await resolve_user(message, session, settings, bridge, token)
    if not target_id:
        await send_text(message, "Reply to the receiver or pass their id.", ephemeral=True)
        return
    receiver = await session.get(User, target_id)
    if receiver is None:
        await send_text(message, "That person has not started the bot yet.", ephemeral=True)
        return
    result = await gift_card(session, player, int(parts[1]), receiver)
    await send_text(message, f"Gift result: {h(result.status)}.")
    if result.status == "ok" and result.character:
        note = (
            f"<b>Gift received</b>\n"
            f"{h(player.first_name)} sent you <b>{h(result.character.name)}</b> "
            f"· card #{result.card_id}."
        )
        try:
            await bot.send_message(receiver.id, note)
        except Exception:
            pass
        await audit(
            bot,
            settings,
            "Gift",
            f"{player.id} → {receiver.id} · {result.character.name} #{result.card_id}",
        )


@router.message(Command("pay"))
async def pay_cmd(message: Message, session: AsyncSession, player: User, settings: Settings, bridge: KurigramBridge) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        await send_text(message, "Use /pay &lt;amount&gt; as a reply, or /pay &lt;user&gt; &lt;amount&gt;.", ephemeral=True)
        return
    if len(parts) == 2:
        amount = parse_listing_price(parts[1])
        if not message.reply_to_message or not message.reply_to_message.from_user or amount is None:
            await send_text(message, "Reply to a player and use /pay &lt;amount&gt;.", ephemeral=True)
            return
        target_id = message.reply_to_message.from_user.id
    else:
        target_id = await resolve_user(message, session, settings, bridge, parts[1])
        amount = parse_listing_price(parts[2])
    if not target_id or amount is None:
        await send_text(message, "Could not read the user or the amount.", ephemeral=True)
        return
    receiver = await session.get(User, target_id)
    if receiver is None:
        await send_text(message, "That person has not started the bot yet.", ephemeral=True)
        return
    status = await pay_coins(session, player, receiver, amount)
    await send_text(message, f"Pay result: {h(status)}.")


@router.message(Command("nguess"))
async def nguess_cmd(message: Message, session: AsyncSession) -> None:
    from ..db import Quiz

    characters = (await session.scalars(select(Character))).all()
    if len(characters) < 4:
        await send_text(message, "Need at least four characters before a quiz.", ephemeral=True)
        return
    answer = random.choice(list(characters))
    decoys = [item for item in characters if item.id != answer.id]
    options = [answer.name] + [item.name for item in random.sample(decoys, 3)]
    random.shuffle(options)
    correct = options.index(answer.name)
    from aiogram.types import InputPollOption

    sent = await message.answer_poll(
        question=f"Which name belongs to {RARITY_BY_KEY[answer.rarity].label}?",
        options=[InputPollOption(text=name[:100]) for name in options],
        type="quiz",
        correct_option_ids=[correct],
        is_anonymous=False,
        explanation=f"{answer.name} is from {answer.series}.",
        description="One correct name. The first try pays 250 coins.",
        shuffle_options=False,
        members_only=message.chat.type != "private",
        open_period=60,
    )
    if sent.poll:
        session.add(Quiz(poll_id=sent.poll.id, user_id=message.from_user.id, correct_index=correct, reward=250, claimed=False))


@router.poll_answer()
async def quiz_answer(answer: PollAnswer, session: AsyncSession, bot) -> None:
    from ..repo import score_quiz

    if answer.user is None:
        return
    status, reward = await score_quiz(session, answer.poll_id, answer.user.id, list(answer.option_ids))
    if status == "ok":
        try:
            await bot.send_message(answer.user.id, f"Quiz correct. +{reward} coins.")
        except Exception:
            return
