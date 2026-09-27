"""Market pool, hclaim, inventory, and extended auction helpers."""

from __future__ import annotations

import random
import secrets

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .db import (
    Auction,
    Card,
    Character,
    ClaimList,
    MarketPool,
    User,
    UserCooldown,
    UserInventory,
)
from .game import RARITIES, RARITY_BY_KEY, format_duration, now_ts, shop_price
from .repo import give_card, premium_active, sync_achievements


def rarity_id_map() -> list[tuple[int, str]]:
    return [(index, item.key) for index, item in enumerate(RARITIES, start=1)]


async def ensure_claim_list(session: AsyncSession) -> None:
    existing = set((await session.scalars(select(ClaimList.rarity_id))).all())
    for rid, key in rarity_id_map():
        if rid in existing:
            continue
        session.add(ClaimList(rarity_id=rid, rarity_key=key, chance=1.0 if key in {"common", "rare", "special"} else 0.0))


async def set_claim_chance(session: AsyncSession, rarity_id: int, chance: float) -> str:
    row = await session.get(ClaimList, rarity_id)
    if row is None:
        return "bad_id"
    row.chance = max(0.0, chance)
    return "ok"


async def claim_list_text(session: AsyncSession) -> str:
    await ensure_claim_list(session)
    rows = (await session.scalars(select(ClaimList).order_by(ClaimList.rarity_id))).all()
    lines = ["<b>Hclaim rarity weights</b>"]
    for row in rows:
        rarity = RARITY_BY_KEY.get(row.rarity_key)
        label = rarity.label if rarity else row.rarity_key
        status = f"{row.chance:g}" if row.chance > 0 else "OFF"
        lines.append(f"{row.rarity_id:02d} · {label} — {status}")
    return "\n".join(lines)


async def hclaim(session: AsyncSession, user: User, settings: Settings) -> tuple[str, Character | None, Card | None]:
    await ensure_claim_list(session)
    moment = now_ts()
    max_claims = 2 if premium_active(user, moment) else 1
    cooldown = settings.hclaim_cooldown_hours * 3600
    if user.last_hclaim and moment - user.last_hclaim < cooldown:
        if user.last_hclaim_count >= max_claims:
            wait = user.last_hclaim + cooldown - moment
            return f"wait:{wait}", None, None
    elif user.last_hclaim and moment - user.last_hclaim >= cooldown:
        user.last_hclaim_count = 0

    rows = (await session.scalars(select(ClaimList).where(ClaimList.chance > 0))).all()
    if not rows:
        return "off", None, None
    weights = [(row.rarity_key, row.chance) for row in rows]
    high = {item.key for item in RARITIES if not item.shop}
    processed: list[tuple[str, float]] = []
    total = 0.0
    for key, chance in weights:
        boost = chance * 3.0 if premium_active(user, moment) and key in high else chance
        total += boost
        processed.append((key, boost))
    if total <= 0:
        return "off", None, None
    pick = random.uniform(0, total)
    cursor = 0.0
    chosen_key = processed[-1][0]
    for key, weight in processed:
        cursor += weight
        if pick <= cursor:
            chosen_key = key
            break
    pool = (await session.scalars(select(Character).where(Character.rarity == chosen_key))).all()
    if not pool:
        pool = (await session.scalars(select(Character))).all()
    if not pool:
        return "empty", None, None
    character = secrets.choice(list(pool))
    card = await give_card(session, user, character, "hclaim")
    user.last_hclaim = moment
    user.last_hclaim_count += 1
    await sync_achievements(session, user)
    return "ok", character, card


async def refresh_market_pool(session: AsyncSession, settings: Settings) -> list[Character]:
    await session.execute(delete(MarketPool))
    characters = list((await session.scalars(select(Character).order_by(func.random()).limit(settings.market_pool_size))).all())
    if not characters:
        all_chars = list((await session.scalars(select(Character))).all())
        characters = random.sample(all_chars, min(settings.market_pool_size, len(all_chars))) if all_chars else []
    moment = now_ts()
    for character in characters:
        session.add(MarketPool(character_id=character.id, added_at=moment))
    await session.flush()
    return characters


async def market_pool_rows(session: AsyncSession, settings: Settings) -> list[Character]:
    ids = list((await session.scalars(select(MarketPool.character_id))).all())
    if not ids:
        return await refresh_market_pool(session, settings)
    rows = list((await session.scalars(select(Character).where(Character.id.in_(ids)))).all())
    if not rows:
        return await refresh_market_pool(session, settings)
    return rows


async def buy_from_pool(session: AsyncSession, buyer: User, character_id: int) -> tuple[str, Card | None]:
    row = await session.get(MarketPool, character_id)
    if row is None:
        return "gone", None
    character = await session.get(Character, character_id)
    if character is None:
        await session.delete(row)
        return "gone", None
    price = int(shop_price(character.rarity, premium_active(buyer)) * 1.2)
    if buyer.balance < price:
        return "funds", None
    buyer.balance -= price
    card = await give_card(session, buyer, character, "cshop")
    await session.delete(row)
    await sync_achievements(session, buyer)
    return "ok", card


async def sell_to_pool_back(session: AsyncSession, seller: User, card_id: int, settings: Settings) -> tuple[str, int]:
    card = await session.get(Card, card_id)
    if card is None or card.user_id != seller.id or card.locked:
        return "card", 0
    character = await session.get(Character, card.character_id)
    if character is None:
        return "card", 0
    payout = int(shop_price(character.rarity, False) * settings.market_sell_back_percent / 100)
    seller.balance += payout
    await session.delete(card)
    await sync_achievements(session, seller)
    return "ok", payout


async def remove_user_character(session: AsyncSession, user_id: int, character_id: int) -> int:
    result = await session.execute(
        delete(Card).where(Card.user_id == user_id, Card.character_id == character_id)
    )
    return int(result.rowcount or 0)


async def list_open_auctions(session: AsyncSession, limit: int = 15) -> list[tuple[Auction, Card, Character]]:
    rows = (
        await session.execute(
            select(Auction, Card, Character)
            .join(Card, Card.id == Auction.card_id)
            .join(Character, Character.id == Card.character_id)
            .where(Auction.status == "open", Auction.ends_at > now_ts())
            .order_by(Auction.ends_at.asc())
            .limit(limit)
        )
    ).all()
    return [(row[0], row[1], row[2]) for row in rows]


async def my_bids(session: AsyncSession, user_id: int) -> list[Auction]:
    return list(
        (
            await session.scalars(
                select(Auction).where(Auction.bidder_id == user_id, Auction.status == "open").order_by(Auction.ends_at)
            )
        ).all()
    )


async def cancel_auction(session: AsyncSession, user_id: int, auction_id: int) -> str:
    auction = await session.get(Auction, auction_id)
    if auction is None or auction.status != "open":
        return "gone"
    if auction.seller_id != user_id:
        return "owner"
    if auction.bidder_id:
        return "has_bids"
    card = await session.get(Card, auction.card_id)
    if card:
        card.locked = False
    auction.status = "cancelled"
    return "ok"


async def hstats_payload(session: AsyncSession, user_id: int) -> dict | None:
    user = await session.get(User, user_id)
    if user is None:
        return None
    rows = (
        await session.execute(
            select(Character.rarity, func.count(Card.id))
            .join(Character, Character.id == Card.character_id)
            .where(Card.user_id == user_id)
            .group_by(Character.rarity)
        )
    ).all()
    total = sum(count for _, count in rows)
    unique = len(rows)
    rank = (
        int(
            await session.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.id.in_(
                        select(Card.user_id).group_by(Card.user_id).having(func.count(Card.id) > total)
                    )
                )
            )
            or 0
        )
        + 1
    )
    return {
        "user": user,
        "total": total,
        "unique": unique,
        "rank": rank,
        "rows": rows,
    }


async def cooldown_left(session: AsyncSession, user_id: int, action: str) -> int:
    row = await session.get(UserCooldown, {"user_id": user_id, "action": action})
    if row is None or row.until_ts <= now_ts():
        return 0
    return row.until_ts - now_ts()


async def set_cooldown(session: AsyncSession, user_id: int, action: str, seconds: int) -> None:
    row = await session.get(UserCooldown, {"user_id": user_id, "action": action})
    until = now_ts() + seconds
    if row is None:
        session.add(UserCooldown(user_id=user_id, action=action, until_ts=until))
    else:
        row.until_ts = until


async def inventory_text(session: AsyncSession, user_id: int) -> str:
    rows = (
        await session.scalars(
            select(UserInventory)
            .where(UserInventory.user_id == user_id, UserInventory.expires_at > now_ts(), UserInventory.uses_remaining > 0)
        )
    ).all()
    if not rows:
        return "<b>Inventory</b>\nEmpty. Buy items from /cshop000000 market refresh shop."
    lines = ["<b>Inventory</b>"]
    for row in rows:
        left = format_duration(row.expires_at - now_ts())
        lines.append(f"• {row.item_id} ×{row.uses_remaining} ({left})")
    lines.append("\n/bomb /steal /skip — see /help")
    return "\n".join(lines)


async def grant_item(session: AsyncSession, user_id: int, item_id: str, uses: int = 1, hours: int = 24) -> None:
    session.add(
        UserInventory(
            user_id=user_id,
            item_id=item_id,
            uses_remaining=uses,
            expires_at=now_ts() + hours * 3600,
        )
    )
