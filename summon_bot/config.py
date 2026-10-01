"""Runtime settings. Secrets come from the environment, never from source."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def resolve_keepalive_url(explicit: str, port: int) -> str:
    """Public self-ping. Empty uses Render, then Railway, then local /ping."""
    raw = (explicit or "").strip()
    if not raw:
        raw = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    if not raw:
        domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
        if domain:
            raw = domain if "://" in domain else f"https://{domain}"
    if not raw:
        return f"http://127.0.0.1:{port}/ping"
    raw = raw.rstrip("/")
    if raw.endswith("/ping") or raw.endswith("/health"):
        return raw
    if "://" in raw and raw.count("/") == 2:
        return f"{raw}/ping"
    return raw


def normalize_database_url(url: str, sqlite_path: Path) -> str:
    url = (url or "").strip()
    if not url:
        return f"sqlite+aiosqlite:///{sqlite_path}"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url.split("://", 1)[0]:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


@dataclass(frozen=True)
class Settings:
    bot_token: str
    owner_id: int
    owner_password: str
    database_url: str
    sqlite_path: Path
    data_dir: Path
    api_id: int
    api_hash: str
    session_string: str
    webhook_url: str
    webhook_secret: str
    webapp_url: str
    host: str
    port: int
    premium_chat_id: int
    premium_star_price: int
    vault_star_price: int
    button_emoji_id: str
    spawn_seconds: int
    spawn_every: int
    starting_balance: int
    daily_reward: int
    refresh_price: int
    hint_price: int
    support_url: str
    log_channel_id: int
    mongo_uri: str
    mongo_db_name: str
    backup_interval_hours: int
    backup_keep: int
    inactive_days: int
    maintenance_interval_hours: int
    keepalive_url: str
    keepalive_seconds: int
    heartbeat_minutes: int
    tagall_limit: int
    official_group_id: int
    hclaim_cooldown_hours: int
    market_pool_size: int
    market_refresh_price: int
    market_sell_back_percent: int

    @property
    def database_backend(self) -> str:
        if self.database_url.startswith("sqlite"):
            return "sqlite"
        if "postgresql" in self.database_url:
            return "postgresql"
        return "other"

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        data_dir = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()
        sqlite_path = Path(os.getenv("SQLITE_PATH", str(data_dir / "summon.db"))).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            bot_token=os.getenv("BOT_TOKEN", "").strip(),
            owner_id=_int("OWNER_ID", 0),
            owner_password=os.getenv("OWNER_PANEL_PASSWORD", "").strip(),
            database_url=normalize_database_url(os.getenv("DATABASE_URL", ""), sqlite_path),
            sqlite_path=sqlite_path,
            data_dir=data_dir,
            api_id=_int("API_ID", 0),
            api_hash=os.getenv("API_HASH", "").strip(),
            session_string=os.getenv("SESSION_STRING", "").strip(),
            webhook_url=os.getenv("WEBHOOK_URL", "").strip().rstrip("/"),
            webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip(),
            webapp_url=os.getenv("WEBAPP_URL", "").strip().rstrip("/"),
            host=os.getenv("HOST", "0.0.0.0"),
            port=_int("PORT", 8080),
            premium_chat_id=_int("PREMIUM_CHAT_ID", 0),
            premium_star_price=max(1, _int("PREMIUM_STAR_PRICE", 75)),
            vault_star_price=max(1, _int("VAULT_STAR_PRICE", 25)),
            button_emoji_id=os.getenv("BUTTON_EMOJI_ID", "").strip(),
            spawn_seconds=max(15, _int("SPAWN_SECONDS", 90)),
            spawn_every=max(5, _int("SPAWN_EVERY", 100)),
            starting_balance=max(0, _int("STARTING_BALANCE", 500)),
            daily_reward=max(0, _int("DAILY_REWARD", 5000)),
            refresh_price=max(0, _int("REFRESH_PRICE", 10000)),
            hint_price=max(0, _int("HINT_PRICE", 50)),
            support_url=os.getenv("SUPPORT_URL", "").strip(),
            log_channel_id=_int("LOG_CHANNEL_ID", 0),
            mongo_uri=os.getenv("MONGO_URI", "").strip(),
            mongo_db_name=os.getenv("MONGO_DB_NAME", "summon_bot").strip() or "summon_bot",
            backup_interval_hours=max(1, _int("BACKUP_INTERVAL_HOURS", 12)),
            backup_keep=max(3, _int("BACKUP_KEEP", 14)),
            inactive_days=max(0, _int("INACTIVE_DAYS", 90)),
            maintenance_interval_hours=max(1, _int("MAINTENANCE_INTERVAL_HOURS", 24)),
            keepalive_url=resolve_keepalive_url(os.getenv("KEEPALIVE_URL", ""), _int("PORT", 8080)),
            keepalive_seconds=max(60, _int("KEEPALIVE_SECONDS", 300)),
            heartbeat_minutes=max(0, _int("HEARTBEAT_MINUTES", 0)),
            tagall_limit=max(5, min(100, _int("TAGALL_LIMIT", 40))),
            official_group_id=_int("OFFICIAL_GROUP_ID", 0),
            hclaim_cooldown_hours=max(1, _int("HCLAIM_COOLDOWN_HOURS", 24)),
            market_pool_size=max(3, _int("MARKET_POOL_SIZE", 10)),
            market_refresh_price=max(0, _int("MARKET_REFRESH_PRICE", 5000)),
            market_sell_back_percent=max(1, min(100, _int("MARKET_SELL_BACK_PERCENT", 50))),
        )

    @property
    def kurigram_enabled(self) -> bool:
        return bool(self.api_id and self.api_hash and (self.bot_token or self.session_string))

    def is_owner(self, user_id: int | None) -> bool:
        return bool(user_id) and user_id == self.owner_id and self.owner_id != 0
