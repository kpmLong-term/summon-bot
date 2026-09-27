"""Inactive account cleanup."""

from __future__ import annotations

import logging

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .db import Card, User
from .game import now_ts

log = logging.getLogger(__name__)


async def cleanup_inactive(session: AsyncSession, settings: Settings) -> int:
    if settings.inactive_days <= 0:
        return 0
    cutoff = now_ts() - settings.inactive_days * 86400
    has_cards = exists().where(Card.user_id == User.id)
    stmt = (
        select(User.id)
        .where(~has_cards)
        .where(User.claims == 0)
        .where(User.balance <= settings.starting_balance)
        .where(User.premium_until < now_ts())
        .where(User.last_seen < cutoff)
        .where(User.id != settings.owner_id)
    )
    ids = list((await session.scalars(stmt)).all())
    if not ids:
        return 0
    await session.execute(delete(User).where(User.id.in_(ids)))
    log.info("purged %s inactive users", len(ids))
    return len(ids)


async def count_users(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(User)) or 0)
