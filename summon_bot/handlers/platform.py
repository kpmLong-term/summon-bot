"""Stars, paid media, inline mode, guest replies, join requests, and Kurigram lookups."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    BotSubscriptionUpdated,
    CallbackQuery,
    ChatJoinRequest,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultsButton,
    InputPaidMediaPhoto,
    InputTextMessageContent,
    LabeledPrice,
    Message,
    PaidMediaPurchased,
    PreCheckoutQuery,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ..bridge import KurigramBridge
from ..config import Settings
from ..db import Character, User
from ..game import PREMIUM_SECONDS, RARITY_BY_KEY
from ..repo import (
    find_character_by_guess,
    get_or_create_user,
    give_card,
    grant_premium,
    premium_active,
    random_of_rarity,
    record_payment,
    search_characters,
)
from ..telegram_ui import h, send_text

log = logging.getLogger(__name__)
router = Router(name="platform")


@router.message(Command("premium"))
async def premium_cmd(message: Message, player: User, settings: Settings) -> None:
    if premium_active(player):
        await send_text(message, "Premium is already active on this account.", ephemeral=True)
        return
    await message.answer_invoice(
        title="Summon Premium",
        description="30 days of a 10% shop discount and the patron achievement. Paid in Telegram Stars.",
        payload=f"premium:{player.id}",
        currency="XTR",
        prices=[LabeledPrice(label="30 days", amount=settings.premium_star_price)],
        provider_token="",
    )


@router.callback_query(F.data == "go:premium")
async def premium_cb(callback: CallbackQuery, player: User, settings: Settings) -> None:
    if callback.message is None:
        await callback.answer()
        return
    if premium_active(player):
        await callback.answer("Already active", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer_invoice(
        title="Summon Premium",
        description="30 days of a 10% shop discount and the patron achievement.",
        payload=f"premium:{player.id}",
        currency="XTR",
        prices=[LabeledPrice(label="30 days", amount=settings.premium_star_price)],
        provider_token="",
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    if query.currency != "XTR":
        await query.answer(ok=False, error_message="This bot charges Telegram Stars only.")
        return
    if not query.invoice_payload.startswith("premium:"):
        await query.answer(ok=False, error_message="Unknown invoice.")
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, session: AsyncSession, player: User) -> None:
    payment = message.successful_payment
    if payment is None:
        return
    recorded = await record_payment(
        session,
        player.id,
        payment.telegram_payment_charge_id,
        payment.invoice_payload,
        payment.total_amount,
    )
    if recorded is None:
        await message.answer("That payment was already applied.")
        return
    if payment.invoice_payload.startswith("premium:"):
        until = await grant_premium(session, player, PREMIUM_SECONDS)
        await message.answer(f"Premium is active until <code>{until}</code> (unix time).")


@router.subscription()
async def subscription_update(event: BotSubscriptionUpdated, session: AsyncSession, settings: Settings) -> None:
    user = await session.get(User, event.user.id)
    if user is None:
        user = await get_or_create_user(session, event.user, settings)
    user.subscription_state = event.state
    if event.state == "active" and event.invoice_payload.startswith("premium:"):
        await grant_premium(session, user, PREMIUM_SECONDS)


@router.message(Command("vault"))
async def vault_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    character = await random_of_rarity(session, "legendary")
    if character is None:
        await send_text(message, "The vault is empty.", ephemeral=True)
        return
    path = character.custom_path or str(settings.data_dir / "art" / f"{character.id}_card.png")
    if premium_active(player):
        card = await give_card(session, player, character, "vault")
        await send_text(message, f"Premium vault pull: <b>{h(character.name)}</b> #{card.id}.", ephemeral=True)
        return
    from aiogram.types import FSInputFile

    await message.answer_paid_media(
        star_count=settings.vault_star_price,
        media=[InputPaidMediaPhoto(media=FSInputFile(path))],
        payload=f"vault:{character.id}:{player.id}",
        caption=f"Unlock a legendary card for {settings.vault_star_price} Stars.",
    )


@router.purchased_paid_media()
async def vault_paid(event: PaidMediaPurchased, session: AsyncSession, settings: Settings, bot: Bot) -> None:
    parts = event.paid_media_payload.split(":")
    if len(parts) != 3 or parts[0] != "vault":
        return
    character_id, user_id = int(parts[1]), int(parts[2])
    if event.from_user.id != user_id:
        return
    user = await session.get(User, user_id)
    character = await session.get(Character, character_id)
    if user is None or character is None:
        return
    card = await give_card(session, user, character, "vault")
    try:
        await bot.send_message(user_id, f"Vault unlocked <b>{h(character.name)}</b> as card #{card.id}.")
    except Exception:
        log.exception("vault notice failed")


@router.message(Command("stars"))
async def stars_cmd(message: Message, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await send_text(message, "Owner only.", ephemeral=True)
        return
    balance = await message.bot.get_my_star_balance()
    await send_text(message, f"Bot Star balance: <b>{balance.amount}</b>.", ephemeral=True)


@router.callback_query(F.data == "op:stars")
async def stars_cb(callback: CallbackQuery, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await callback.answer("Owner only", show_alert=True)
        return
    balance = await callback.bot.get_my_star_balance()
    await callback.answer(f"{balance.amount} Stars", show_alert=True)


@router.message(Command("refund"))
async def refund_cmd(message: Message, session: AsyncSession, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await send_text(message, "Owner only.", ephemeral=True)
        return
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit():
        await send_text(message, "Use /refund &lt;user id&gt; &lt;telegram charge id&gt;.", ephemeral=True)
        return
    from ..db import Payment

    await message.bot.refund_star_payment(user_id=int(parts[1]), telegram_payment_charge_id=parts[2])
    payment = await session.get(Payment, parts[2])
    if payment:
        payment.refunded = True
    await send_text(message, "Refund sent.", ephemeral=True)


@router.message(Command("sublink"))
async def sublink_cmd(message: Message, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await send_text(message, "Owner only.", ephemeral=True)
        return
    if not settings.premium_chat_id:
        await send_text(message, "Set PREMIUM_CHAT_ID to a channel that sells subscriptions.", ephemeral=True)
        return
    link = await message.bot.create_chat_subscription_invite_link(
        chat_id=settings.premium_chat_id,
        subscription_period=2_592_000,
        subscription_price=settings.premium_star_price,
        name="Summon premium",
    )
    await send_text(message, f"Subscription invite:\n{h(link.invite_link)}", ephemeral=True)


@router.callback_query(F.data == "op:sublink")
async def sublink_cb(callback: CallbackQuery, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await callback.answer("Owner only", show_alert=True)
        return
    if not settings.premium_chat_id:
        await callback.answer("PREMIUM_CHAT_ID is empty", show_alert=True)
        return
    await callback.answer("Use /sublink so the invite is not stuck on this button", show_alert=True)


@router.message(Command("emoji"))
async def emoji_cmd(message: Message, player: User, settings: Settings, bridge: KurigramBridge) -> None:
    if not await has_power_owner(player, settings):
        await send_text(message, "Owner only.", ephemeral=True)
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await send_text(message, "Use /emoji &lt;custom emoji id&gt;.", ephemeral=True)
        return
    emoji_id = parts[1]
    bot_count = 0
    try:
        stickers = await message.bot.get_custom_emoji_stickers(custom_emoji_ids=[emoji_id])
        bot_count = len(stickers)
    except Exception as exc:
        await send_text(message, f"Bot API lookup failed: {h(exc)}", ephemeral=True)
        return
    mtproto = await bridge.custom_emoji_count(int(emoji_id))
    extra = f" Kurigram documents: {mtproto}." if mtproto is not None else " Kurigram is off (set API_ID and API_HASH)."
    await send_text(message, f"Bot API stickers: {bot_count}.{extra}", ephemeral=True)


def has_power_owner(player: User, settings: Settings) -> bool:
    return settings.is_owner(player.id)


@router.message(Command("gifts"))
async def gifts_cmd(message: Message, player: User, settings: Settings) -> None:
    if not settings.is_owner(player.id):
        await send_text(message, "Owner only.", ephemeral=True)
        return
    gifts = await message.bot.get_available_gifts()
    count = len(gifts.gifts)
    await send_text(
        message,
        f"Telegram currently offers {count} gifts this bot can inspect. Sending one spends Stars, so this command only lists the count.",
        ephemeral=True,
    )


@router.inline_query()
async def inline_search(query: InlineQuery, session: AsyncSession) -> None:
    rows = await search_characters(session, query.query, limit=12)
    results = []
    for character in rows:
        rarity = RARITY_BY_KEY.get(character.rarity)
        label = rarity.label if rarity else character.rarity
        results.append(
            InlineQueryResultArticle(
                id=str(character.id),
                title=character.name,
                description=f"{label} · {character.series} · caught {character.catch_count}",
                input_message_content=InputTextMessageContent(
                    message_text=f"<b>{h(character.name)}</b>\n{h(label)} · {h(character.series)}\nCaught {character.catch_count} times."
                ),
            )
        )
    button = None
    if query.query:
        guess = await find_character_by_guess(session, query.query)
        if guess:
            button = InlineQueryResultsButton(text=f"Exact: {guess.name[:24]}", start_parameter="help")
    await query.answer(results, cache_time=5, is_personal=True, button=button)


@router.guest_message()
async def guest(message: Message, bot: Bot) -> None:
    if not message.guest_query_id:
        return
    await bot.answer_guest_query(
        guest_query_id=message.guest_query_id,
        result=InlineQueryResultArticle(
            id="guest-summon",
            title="Summon",
            description="Add the bot to a group to catch characters.",
            input_message_content=InputTextMessageContent(
                message_text="<b>Summon</b>\nAdd the bot to a group. Characters appear after enough messages. Type the name to catch them."
            ),
        ),
    )


@router.chat_join_request()
async def join_request(event: ChatJoinRequest, session: AsyncSession, bot: Bot, settings: Settings) -> None:
    if not settings.premium_chat_id or event.chat.id != settings.premium_chat_id:
        return
    user = await session.get(User, event.from_user.id)
    if user and premium_active(user):
        await bot.approve_chat_join_request(event.chat.id, event.from_user.id)
        return
    await bot.decline_chat_join_request(event.chat.id, event.from_user.id)


@router.my_chat_member()
async def bot_membership(event, session: AsyncSession, settings: Settings, bot: Bot) -> None:
    from ..audit import audit
    from ..repo import ensure_group

    chat = event.chat
    if chat.type not in {"group", "supergroup"}:
        return
    status = event.new_chat_member.status
    if status in {"member", "administrator"}:
        await ensure_group(session, chat.id, chat.title or "", settings)
        await audit(
            bot,
            settings,
            "Group joined",
            f"{h(chat.title)} · {chat.id} · by {event.from_user.full_name} ({event.from_user.id})",
        )
    elif status in {"left", "kicked"}:
        from ..db import Group

        group = await session.get(Group, chat.id)
        if group:
            group.enabled = False
        await audit(bot, settings, "Group left", f"{h(chat.title)} · {chat.id}")
