"""Inactive account cleanup."""

from __future__ import annotations

import logging

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .db import Auction, Card, Listing, User
from .game import now_ts

log = logging.getLogger(__name__)


async def cleanup_inactive(session: AsyncSession, settings: Settings) -> int:
    if settings.inactive_days <= 0:
        return 0
    cutoff = now_ts() - settings.inactive_days * 86400
    seen = func.coalesce(func.nullif(User.last_seen, 0), User.created_at)
    has_cards = exists().where(Card.user_id == User.id)
    selling = exists().where(Listing.seller_id == User.id)
    bidding = exists().where(or_(Auction.seller_id == User.id, Auction.bidder_id == User.id))
    stmt = (
        select(User.id)
        .where(~has_cards)
        .where(~selling)
        .where(~bidding)
        .where(User.claims == 0)
        .where(User.balance <= settings.starting_balance)
        .where(User.premium_until < now_ts())
        .where(seen > 0)
        .where(seen < cutoff)
        .where(User.id != settings.owner_id)
        .limit(settings.inactive_batch)
    )
    ids = list((await session.scalars(stmt)).all())
    if not ids:
        return 0
    await session.execute(delete(User).where(User.id.in_(ids)))
    log.info("purged %s inactive users", len(ids))
    return len(ids)


async def count_users(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(User)) or 0)
