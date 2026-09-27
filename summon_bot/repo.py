"""Database operations for the collector game."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .db import (
    Achievement,
    Alias,
    Auction,
    Card,
    Character,
    Code,
    CodeUse,
    Group,
    GroupMember,
    Listing,
    Payment,
    Quiz,
    Spawn,
    Sudo,
    User,
    Warning,
    Weight,
)
from .game import (
    MIN_LISTING_PRICE,
    RARITIES,
    RARITY_BY_KEY,
    achievement_keys,
    daily_payout,
    next_streak,
    normalize_name,
    now_ts,
    pick_weighted,
    shop_price,
)


@dataclass
class ClaimResult:
    ok: bool
    reason: str
    card_id: int | None = None
    character: Character | None = None
    new_achievements: tuple[str, ...] = ()


@dataclass
class GiftResult:
    status: str
    card_id: int | None = None
    character: Character | None = None


def premium_active(user: User, moment: int | None = None) -> bool:
    return user.premium_until > (now_ts() if moment is None else moment)


def _today() -> int:
    return datetime.now(timezone.utc).date().toordinal()


def roll_quest_day(user: User) -> None:
    today = _today()
    if user.quest_day != today:
        user.quest_day = today
        user.quest_catch = 0
        user.quest_msgs = 0
        user.quest_catch_claimed = False
        user.quest_msgs_claimed = False
        user.quest_daily_claimed = False


async def get_or_create_user(session: AsyncSession, tg_user, settings: Settings) -> User:
    user = await session.get(User, tg_user.id)
    if user is None:
        user = User(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name or "",
            balance=settings.starting_balance,
            created_at=now_ts(),
            last_seen=now_ts(),
            font="plain",
            hmode="all",
        )
        session.add(user)
        await session.flush()
        return user
    user.username = tg_user.username
    if tg_user.first_name:
        user.first_name = tg_user.first_name
    user.last_seen = now_ts()
    return user


async def track_group_member(session: AsyncSession, chat_id: int, tg_user) -> None:
    row = await session.get(GroupMember, {"chat_id": chat_id, "user_id": tg_user.id})
    if row is None:
        session.add(
            GroupMember(
                chat_id=chat_id,
                user_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name or "",
                last_seen=now_ts(),
            )
        )
    else:
        row.username = tg_user.username
        if tg_user.first_name:
            row.first_name = tg_user.first_name
        row.last_seen = now_ts()


async def user_by_username(session: AsyncSession, username: str) -> User | None:
    key = username.lstrip("@").casefold()
    return await session.scalar(select(User).where(func.lower(User.username) == key))


async def ensure_group(session: AsyncSession, chat_id: int, title: str, settings: Settings) -> Group:
    group = await session.get(Group, chat_id)
    if group is None:
        group = Group(chat_id=chat_id, title=title or "", spawn_every=settings.spawn_every, message_count=0, enabled=True)
        session.add(group)
        await session.flush()
    elif title and group.title != title:
        group.title = title
    return group


async def weights_for(session: AsyncSession, chat_id: int) -> list[tuple[str, int]]:
    rows = (await session.scalars(select(Weight).where(Weight.chat_id == chat_id))).all()
    if not rows:
        rows = (await session.scalars(select(Weight).where(Weight.chat_id == 0))).all()
    if not rows:
        return [(item.key, item.weight) for item in RARITIES]
    return [(row.rarity, row.weight) for row in rows if row.weight > 0 and row.rarity in RARITY_BY_KEY]


async def set_weight(session: AsyncSession, chat_id: int, rarity: str, weight: int) -> None:
    row = await session.get(Weight, {"chat_id": chat_id, "rarity": rarity})
    if row is None:
        session.add(Weight(chat_id=chat_id, rarity=rarity, weight=weight))
    else:
        row.weight = weight


async def note_group_message(session: AsyncSession, group: Group, user: User) -> bool:
    """Count a chat message. True when a spawn should be posted."""
    roll_quest_day(user)
    user.quest_msgs += 1
    if not group.enabled:
        return False
    active = await session.get(Spawn, group.chat_id)
    if active and active.expires_at > now_ts():
        return False
    if active and active.expires_at <= now_ts():
        await session.delete(active)
        await session.flush()
    group.message_count += 1
    if group.message_count < group.spawn_every:
        return False
    group.message_count = 0
    return True


async def choose_character(session: AsyncSession, chat_id: int) -> Character | None:
    weights = await weights_for(session, chat_id)
    characters = (await session.scalars(select(Character))).all()
    by_rarity: dict[str, list[Character]] = {}
    for character in characters:
        by_rarity.setdefault(character.rarity, []).append(character)
    usable = [(key, weight) for key, weight in weights if by_rarity.get(key)]
    if not usable:
        return None
    rarity = pick_weighted(usable)
    pool = by_rarity[rarity]
    return secrets.choice(pool)


async def open_spawn(session: AsyncSession, chat_id: int, character_id: int, message_id: int, seconds: int) -> Spawn:
    current = await session.get(Spawn, chat_id)
    if current:
        await session.delete(current)
        await session.flush()
    spawn = Spawn(
        chat_id=chat_id,
        character_id=character_id,
        message_id=message_id,
        expires_at=now_ts() + seconds,
        hint_used=False,
    )
    session.add(spawn)
    await session.flush()
    return spawn


async def find_character_by_guess(session: AsyncSession, text: str) -> Character | None:
    key = normalize_name(text)
    if not key:
        return None
    character = await session.scalar(select(Character).where(Character.name_key == key))
    if character:
        return character
    alias = await session.get(Alias, key)
    if alias is None:
        return None
    return await session.get(Character, alias.character_id)


async def owned_rarities(session: AsyncSession, user_id: int) -> set[str]:
    rows = await session.execute(
        select(Character.rarity)
        .join(Card, Card.character_id == Character.id)
        .where(Card.user_id == user_id)
        .distinct()
    )
    return {row[0] for row in rows.all()}


async def sync_achievements(session: AsyncSession, user: User) -> tuple[str, ...]:
    owned = await owned_rarities(session, user.id)
    wanted = achievement_keys(
        claims=user.claims,
        best_streak=user.best_streak,
        balance=user.balance,
        owned_rarities=owned,
        premium=premium_active(user),
    )
    have = set(
        (await session.scalars(select(Achievement.key).where(Achievement.user_id == user.id))).all()
    )
    fresh = []
    for key in sorted(wanted - have):
        session.add(Achievement(user_id=user.id, key=key, at=now_ts()))
        fresh.append(key)
    return tuple(fresh)


async def give_card(session: AsyncSession, user: User, character: Character, source: str) -> Card:
    card = Card(
        user_id=user.id,
        character_id=character.id,
        source=source,
        locked=False,
        obtained_at=now_ts(),
    )
    character.catch_count += 1
    session.add(card)
    await session.flush()
    return card


async def try_claim(session: AsyncSession, chat_id: int, user: User, text: str) -> ClaimResult:
    spawn = await session.get(Spawn, chat_id)
    if spawn is None:
        return ClaimResult(False, "none")
    if spawn.expires_at <= now_ts():
        await session.delete(spawn)
        return ClaimResult(False, "expired")
    character = await session.get(Character, spawn.character_id)
    if character is None:
        await session.delete(spawn)
        return ClaimResult(False, "missing")
    guess = await find_character_by_guess(session, text)
    if guess is None or guess.id != character.id:
        return ClaimResult(False, "wrong")
    await session.delete(spawn)
    if user.banned:
        return ClaimResult(False, "banned")
    card = await give_card(session, user, character, "spawn")
    user.claims += 1
    roll_quest_day(user)
    user.quest_catch += 1
    fresh = await sync_achievements(session, user)
    return ClaimResult(True, "ok", card_id=card.id, character=character, new_achievements=fresh)


async def buy_hint(session: AsyncSession, chat_id: int, user: User, price: int) -> tuple[str, str]:
    spawn = await session.get(Spawn, chat_id)
    if spawn is None or spawn.expires_at <= now_ts():
        return "none", ""
    character = await session.get(Character, spawn.character_id)
    if character is None:
        return "none", ""
    if spawn.hint_used:
        from .game import hint_text

        return "repeat", hint_text(character.name, character.series)
    if user.balance < price:
        return "funds", ""
    user.balance -= price
    spawn.hint_used = True
    from .game import hint_text

    return "ok", hint_text(character.name, character.series)


async def collection_count(session: AsyncSession, user_id: int, hmode: str) -> int:
    stmt = select(func.count()).select_from(Card).where(Card.user_id == user_id)
    if hmode != "all":
        stmt = stmt.join(Character, Character.id == Card.character_id).where(Character.rarity == hmode)
    return int(await session.scalar(stmt) or 0)


async def collection_slice(session: AsyncSession, user_id: int, hmode: str, offset: int) -> tuple[Card, Character] | None:
    stmt = (
        select(Card, Character)
        .join(Character, Character.id == Card.character_id)
        .where(Card.user_id == user_id)
        .order_by(Card.id.desc())
    )
    if hmode != "all":
        stmt = stmt.where(Character.rarity == hmode)
    row = (await session.execute(stmt.offset(offset).limit(1))).first()
    if row is None:
        return None
    return row[0], row[1]


async def search_characters(session: AsyncSession, query: str, limit: int = 10) -> list[Character]:
    key = normalize_name(query)
    stmt = select(Character).order_by(Character.catch_count.desc(), Character.name).limit(limit)
    if key:
        stmt = select(Character).where(Character.name_key.contains(key)).order_by(Character.name).limit(limit)
    return list((await session.scalars(stmt)).all())


async def claim_daily(session: AsyncSession, user: User, base: int) -> tuple[str, int, int]:
    moment = now_ts()
    if user.last_daily and moment - user.last_daily < 24 * 60 * 60:
        return "wait", 0, user.last_daily + 24 * 60 * 60 - moment
    streak = next_streak(user.last_daily, user.streak, moment)
    payout = daily_payout(streak, base)
    user.streak = streak
    user.best_streak = max(user.best_streak, streak)
    user.last_daily = moment
    user.balance += payout
    roll_quest_day(user)
    await sync_achievements(session, user)
    return "ok", payout, streak


async def mark_spin(session: AsyncSession, user: User, reward: int) -> str:
    moment = now_ts()
    if user.last_spin and moment - user.last_spin < 24 * 60 * 60:
        return "wait"
    user.last_spin = moment
    user.balance += reward
    await sync_achievements(session, user)
    return "ok"


async def buy_character(session: AsyncSession, user: User, character: Character) -> tuple[str, Card | None]:
    price = shop_price(character.rarity, premium_active(user))
    if user.balance < price:
        return "funds", None
    user.balance -= price
    card = await give_card(session, user, character, "shop")
    await sync_achievements(session, user)
    return "ok", card


async def random_of_rarity(session: AsyncSession, rarity: str) -> Character | None:
    rows = (await session.scalars(select(Character).where(Character.rarity == rarity))).all()
    if not rows:
        return None
    return secrets.choice(list(rows))


async def create_listing(session: AsyncSession, user: User, card_id: int, price: int) -> tuple[str, Listing | None]:
    if price < MIN_LISTING_PRICE:
        return "price", None
    card = await session.get(Card, card_id)
    if card is None or card.user_id != user.id:
        return "card", None
    if card.locked:
        return "locked", None
    card.locked = True
    listing = Listing(seller_id=user.id, card_id=card.id, price=price, created_at=now_ts())
    session.add(listing)
    await session.flush()
    return "ok", listing


async def market_page(session: AsyncSession, offset: int, limit: int = 5) -> list[tuple[Listing, Card, Character]]:
    rows = (
        await session.execute(
            select(Listing, Card, Character)
            .join(Card, Card.id == Listing.card_id)
            .join(Character, Character.id == Card.character_id)
            .order_by(Listing.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [(row[0], row[1], row[2]) for row in rows]


async def buy_listing(session: AsyncSession, buyer: User, listing_id: int) -> tuple[str, int]:
    listing = await session.get(Listing, listing_id)
    if listing is None:
        return "gone", 0
    if listing.seller_id == buyer.id:
        return "self", 0
    if buyer.balance < listing.price:
        return "funds", 0
    card = await session.get(Card, listing.card_id)
    seller = await session.get(User, listing.seller_id)
    if card is None or seller is None or card.user_id != seller.id:
        await session.delete(listing)
        if card:
            card.locked = False
        return "gone", 0
    price = listing.price
    buyer.balance -= price
    seller.balance += price
    card.user_id = buyer.id
    card.locked = False
    card.source = "market"
    if seller.favorite_card_id == card.id:
        seller.favorite_card_id = None
    await session.delete(listing)
    await sync_achievements(session, buyer)
    await sync_achievements(session, seller)
    return "ok", price


async def open_auction(session: AsyncSession, user: User, card_id: int, start_price: int, hours: int) -> tuple[str, Auction | None]:
    if start_price < MIN_LISTING_PRICE:
        return "price", None
    card = await session.get(Card, card_id)
    if card is None or card.user_id != user.id:
        return "card", None
    if card.locked:
        return "locked", None
    card.locked = True
    auction = Auction(
        seller_id=user.id,
        card_id=card.id,
        start_price=start_price,
        current_bid=0,
        bidder_id=None,
        ends_at=now_ts() + max(1, hours) * 3600,
        status="open",
    )
    session.add(auction)
    await session.flush()
    return "ok", auction


async def place_bid(session: AsyncSession, auction_id: int, bidder: User, amount: int) -> str:
    auction = await session.get(Auction, auction_id)
    if auction is None or auction.status != "open" or auction.ends_at <= now_ts():
        return "closed"
    if bidder.id == auction.seller_id:
        return "self"
    minimum = auction.start_price if not auction.bidder_id else auction.current_bid + 1
    if amount < minimum:
        return "low"
    if bidder.balance < amount:
        return "funds"
    if auction.bidder_id:
        previous = await session.get(User, auction.bidder_id)
        if previous:
            previous.balance += auction.current_bid
    bidder.balance -= amount
    auction.current_bid = amount
    auction.bidder_id = bidder.id
    return "ok"


async def close_due_auctions(session: AsyncSession) -> list[Auction]:
    moment = now_ts()
    due = (
        await session.scalars(select(Auction).where(Auction.status == "open", Auction.ends_at <= moment))
    ).all()
    closed: list[Auction] = []
    for auction in due:
        card = await session.get(Card, auction.card_id)
        seller = await session.get(User, auction.seller_id)
        if card:
            card.locked = False
        if auction.bidder_id and seller and card and card.user_id == seller.id:
            seller.balance += auction.current_bid
            card.user_id = auction.bidder_id
            card.source = "auction"
            if seller.favorite_card_id == card.id:
                seller.favorite_card_id = None
            winner = await session.get(User, auction.bidder_id)
            if winner:
                await sync_achievements(session, winner)
            await sync_achievements(session, seller)
        elif auction.bidder_id:
            previous = await session.get(User, auction.bidder_id)
            if previous:
                previous.balance += auction.current_bid
        auction.status = "closed"
        closed.append(auction)
    return closed


async def gift_card(session: AsyncSession, owner: User, card_id: int, receiver: User) -> GiftResult:
    if owner.id == receiver.id:
        return GiftResult("self")
    card = await session.get(Card, card_id)
    if card is None or card.user_id != owner.id:
        return GiftResult("card")
    if card.locked:
        return GiftResult("locked")
    character = await session.get(Character, card.character_id)
    card.user_id = receiver.id
    card.source = "gift"
    if owner.favorite_card_id == card.id:
        owner.favorite_card_id = None
    await sync_achievements(session, receiver)
    return GiftResult("ok", card_id=card.id, character=character)


async def pay_coins(session: AsyncSession, sender: User, receiver: User, amount: int) -> str:
    if amount <= 0:
        return "amount"
    if sender.id == receiver.id:
        return "self"
    if sender.balance < amount:
        return "funds"
    sender.balance -= amount
    receiver.balance += amount
    await sync_achievements(session, receiver)
    return "ok"


async def adjust_balance(session: AsyncSession, user: User, delta: int) -> None:
    user.balance = max(0, user.balance + delta)
    await sync_achievements(session, user)


async def redeem(session: AsyncSession, user: User, raw_code: str) -> tuple[str, str]:
    code_key = raw_code.strip().upper()
    if not code_key:
        return "missing", ""
    code = await session.get(Code, code_key)
    if code is None:
        return "bad", ""
    used = await session.get(CodeUse, {"code": code_key, "user_id": user.id})
    if used:
        return "used", ""
    if code.uses_left <= 0:
        return "bad", ""
    session.add(CodeUse(code=code_key, user_id=user.id))
    code.uses_left -= 1
    notes = []
    if code.coins:
        user.balance += code.coins
        notes.append(f"{code.coins} coins")
    if code.character_id:
        character = await session.get(Character, code.character_id)
        if character:
            card = await give_card(session, user, character, "code")
            notes.append(f"{character.name} #{card.id}")
    await sync_achievements(session, user)
    return "ok", ", ".join(notes) or "nothing"


async def create_code(session: AsyncSession, coins: int, character_id: int | None, uses: int) -> Code:
    code = Code(
        code=secrets.token_hex(4).upper(),
        coins=max(0, coins),
        character_id=character_id,
        uses_left=max(1, uses),
    )
    session.add(code)
    await session.flush()
    return code


async def grant_premium(session: AsyncSession, user: User, seconds: int) -> int:
    start = max(now_ts(), user.premium_until)
    user.premium_until = start + seconds
    await sync_achievements(session, user)
    return user.premium_until


async def record_payment(session: AsyncSession, user_id: int, charge_id: str, payload: str, amount: int) -> Payment | None:
    if await session.get(Payment, charge_id):
        return None
    payment = Payment(charge_id=charge_id, user_id=user_id, payload=payload, amount=amount, at=now_ts(), refunded=False)
    session.add(payment)
    await session.flush()
    return payment


async def leaderboard(session: AsyncSession, kind: str, limit: int = 10) -> list[User]:
    if kind == "coins":
        stmt = select(User).where(User.banned.is_(False)).order_by(User.balance.desc(), User.id).limit(limit)
    else:
        stmt = (
            select(User)
            .join(Card, Card.user_id == User.id)
            .where(User.banned.is_(False))
            .group_by(User.id)
            .order_by(func.count(Card.id).desc(), User.id)
            .limit(limit)
        )
    return list((await session.scalars(stmt)).all())


async def card_count(session: AsyncSession, user_id: int) -> int:
    return int(await session.scalar(select(func.count()).select_from(Card).where(Card.user_id == user_id)) or 0)


async def global_counts(session: AsyncSession) -> tuple[int, int, int]:
    users = int(await session.scalar(select(func.count()).select_from(User)) or 0)
    characters = int(await session.scalar(select(func.count()).select_from(Character)) or 0)
    groups = int(await session.scalar(select(func.count()).select_from(Group)) or 0)
    return users, characters, groups


async def has_power(session: AsyncSession, settings: Settings, user_id: int, power: str) -> bool:
    if settings.is_owner(user_id):
        return True
    sudo = await session.get(Sudo, user_id)
    if sudo is None:
        return False
    return bool(getattr(sudo, power, False))


async def add_warning(session: AsyncSession, chat_id: int, user_id: int, reason: str) -> int:
    session.add(Warning(chat_id=chat_id, user_id=user_id, reason=reason[:255], at=now_ts()))
    await session.flush()
    return int(
        await session.scalar(
            select(func.count()).select_from(Warning).where(Warning.chat_id == chat_id, Warning.user_id == user_id)
        )
        or 0
    )


async def clear_user_cards(session: AsyncSession, user_id: int) -> int:
    await session.execute(delete(Listing).where(Listing.seller_id == user_id))
    await session.execute(delete(Auction).where(Auction.seller_id == user_id, Auction.status == "open"))
    result = await session.execute(delete(Card).where(Card.user_id == user_id))
    user = await session.get(User, user_id)
    if user:
        user.favorite_card_id = None
    return int(result.rowcount or 0)


async def score_quiz(session: AsyncSession, poll_id: str, user_id: int, option_ids: list[int]) -> tuple[str, int]:
    quiz = await session.get(Quiz, poll_id)
    if quiz is None:
        return "unknown", 0
    if quiz.user_id != user_id:
        return "owner", 0
    if quiz.claimed:
        return "used", 0
    quiz.claimed = True
    if quiz.correct_index not in option_ids:
        return "wrong", 0
    user = await session.get(User, user_id)
    if user is None:
        return "wrong", 0
    user.balance += quiz.reward
    await sync_achievements(session, user)
    return "ok", quiz.reward


async def claim_quest(session: AsyncSession, user: User, key: str) -> tuple[str, int]:
    roll_quest_day(user)
    rewards = {"catch": (1, "quest_catch", "quest_catch_claimed", 200), "msgs": (15, "quest_msgs", "quest_msgs_claimed", 200), "daily": (1, None, "quest_daily_claimed", 300)}
    if key not in rewards:
        return "bad", 0
    goal, progress_attr, claimed_attr, reward = rewards[key]
    if getattr(user, claimed_attr):
        return "used", 0
    if key == "daily":
        ready = user.last_daily > 0 and _today() == datetime.fromtimestamp(user.last_daily, timezone.utc).date().toordinal()
    else:
        ready = getattr(user, progress_attr) >= goal
    if not ready:
        return "progress", 0
    setattr(user, claimed_attr, True)
    user.balance += reward
    await sync_achievements(session, user)
    return "ok", reward
