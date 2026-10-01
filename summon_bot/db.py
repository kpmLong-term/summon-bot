"""SQLAlchemy models. PostgreSQL when it answers, SQLite when it does not."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import Settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    balance: Mapped[int] = mapped_column(Integer, default=0)
    premium_until: Mapped[int] = mapped_column(Integer, default=0)
    last_daily: Mapped[int] = mapped_column(Integer, default=0)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    best_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_spin: Mapped[int] = mapped_column(Integer, default=0)
    claims: Mapped[int] = mapped_column(Integer, default=0)
    favorite_card_id: Mapped[int | None] = mapped_column(Integer)
    hmode: Mapped[str] = mapped_column(String(32), default="all")
    font: Mapped[str] = mapped_column(String(16), default="plain")
    glow: Mapped[bool] = mapped_column(Boolean, default=False)
    banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(Integer, default=0)
    quest_day: Mapped[int] = mapped_column(Integer, default=0)
    quest_catch: Mapped[int] = mapped_column(Integer, default=0)
    quest_msgs: Mapped[int] = mapped_column(Integer, default=0)
    quest_catch_claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    quest_msgs_claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    quest_daily_claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    subscription_state: Mapped[str] = mapped_column(String(16), default="")
    last_seen: Mapped[int] = mapped_column(Integer, default=0)
    last_hclaim: Mapped[int] = mapped_column(Integer, default=0)
    last_hclaim_count: Mapped[int] = mapped_column(Integer, default=0)


class Group(Base):
    __tablename__ = "groups"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    spawn_every: Mapped[int] = mapped_column(Integer, default=100)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    welcome: Mapped[str] = mapped_column(String(500), default="")
    warn_limit: Mapped[int] = mapped_column(Integer, default=3)


class GroupMember(Base):
    __tablename__ = "group_members"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(128), default="")
    last_seen: Mapped[int] = mapped_column(Integer, default=0)


class Character(Base):
    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    name_key: Mapped[str] = mapped_column(String(128), unique=True)
    series: Mapped[str] = mapped_column(String(128), default="")
    rarity: Mapped[str] = mapped_column(String(32), index=True)
    custom_path: Mapped[str | None] = mapped_column(String(512))
    catch_count: Mapped[int] = mapped_column(Integer, default=0)


class Alias(Base):
    __tablename__ = "aliases"
    name_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"))
    source: Mapped[str] = mapped_column(String(24))
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    obtained_at: Mapped[int] = mapped_column(Integer)


class Spawn(Base):
    __tablename__ = "spawns"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    character_id: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[int] = mapped_column(Integer)
    hint_used: Mapped[bool] = mapped_column(Boolean, default=False)


class Weight(Base):
    __tablename__ = "rarity_weights"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rarity: Mapped[str] = mapped_column(String(32), primary_key=True)
    weight: Mapped[int] = mapped_column(Integer)


class Listing(Base):
    __tablename__ = "listings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(BigInteger, index=True)
    card_id: Mapped[int] = mapped_column(Integer, unique=True)
    price: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer)


class Auction(Base):
    __tablename__ = "auctions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(BigInteger, index=True)
    card_id: Mapped[int] = mapped_column(Integer, unique=True)
    start_price: Mapped[int] = mapped_column(Integer)
    current_bid: Mapped[int] = mapped_column(Integer, default=0)
    bidder_id: Mapped[int | None] = mapped_column(BigInteger)
    ends_at: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(16), default="open")


class Code(Base):
    __tablename__ = "codes"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    coins: Mapped[int] = mapped_column(Integer, default=0)
    character_id: Mapped[int | None] = mapped_column(Integer)
    uses_left: Mapped[int] = mapped_column(Integer, default=1)


class CodeUse(Base):
    __tablename__ = "code_uses"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class Sudo(Base):
    __tablename__ = "sudo"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    moderate: Mapped[bool] = mapped_column(Boolean, default=True)
    spawn: Mapped[bool] = mapped_column(Boolean, default=True)
    chars: Mapped[bool] = mapped_column(Boolean, default=False)
    economy: Mapped[bool] = mapped_column(Boolean, default=False)


class Warning(Base):
    __tablename__ = "warnings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    reason: Mapped[str] = mapped_column(String(255), default="")
    at: Mapped[int] = mapped_column(Integer)


class Achievement(Base):
    __tablename__ = "achievements"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    at: Mapped[int] = mapped_column(Integer)


class Quiz(Base):
    __tablename__ = "quizzes"
    poll_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    correct_index: Mapped[int] = mapped_column(Integer)
    reward: Mapped[int] = mapped_column(Integer)
    claimed: Mapped[bool] = mapped_column(Boolean, default=False)


class Payment(Base):
    __tablename__ = "payments"
    charge_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    payload: Mapped[str] = mapped_column(String(128))
    amount: Mapped[int] = mapped_column(Integer)
    at: Mapped[int] = mapped_column(Integer)
    refunded: Mapped[bool] = mapped_column(Boolean, default=False)


class MediaCache(Base):
    __tablename__ = "media_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(256))


class ClaimList(Base):
    __tablename__ = "claim_list"
    rarity_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rarity_key: Mapped[str] = mapped_column(String(32))
    chance: Mapped[float] = mapped_column(default=1.0)


class MarketPool(Base):
    __tablename__ = "market_pool"
    character_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    added_at: Mapped[int] = mapped_column(Integer, default=0)


class UserInventory(Base):
    __tablename__ = "user_inventory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    item_id: Mapped[str] = mapped_column(String(32))
    uses_remaining: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[int] = mapped_column(Integer)


class UserCooldown(Base):
    __tablename__ = "user_cooldowns"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    action: Mapped[str] = mapped_column(String(16), primary_key=True)
    until_ts: Mapped[int] = mapped_column(Integer, default=0)


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.backend = "sqlite"
        self.engine = None
        self.factory = None
        self._bind(settings.database_url)

    def _bind(self, url: str) -> None:
        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("postgresql"):
            kwargs["connect_args"] = {"timeout": 5}
        self.engine = create_async_engine(url, **kwargs)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        if url.startswith("sqlite"):
            self.backend = "sqlite"
        elif "postgresql" in url:
            self.backend = "postgresql"
        else:
            self.backend = "other"

        @event.listens_for(self.engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
            if self.engine.dialect.name == "sqlite":
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

    async def _create(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_add_group_columns)

    async def init(self) -> None:
        try:
            await self._create()
            return
        except Exception as exc:
            if self.backend == "sqlite":
                raise
            log.warning("PostgreSQL unavailable (%s); using SQLite at %s", type(exc).__name__, self.settings.sqlite_path)
        await self.engine.dispose()
        self._bind(f"sqlite+aiosqlite:///{self.settings.sqlite_path}")
        await self._create()

    async def close(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


def _add_group_columns(sync_conn) -> None:
    cols = {col["name"] for col in inspect(sync_conn).get_columns("groups")}
    if "welcome" not in cols:
        sync_conn.execute(text("ALTER TABLE groups ADD COLUMN welcome VARCHAR(500) DEFAULT ''"))
    if "warn_limit" not in cols:
        sync_conn.execute(text("ALTER TABLE groups ADD COLUMN warn_limit INTEGER DEFAULT 3"))
