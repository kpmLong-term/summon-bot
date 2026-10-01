import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from sqlalchemy import select

from summon_bot.art import render_card, render_spawn
from summon_bot.config import Settings, normalize_database_url, resolve_keepalive_url
from summon_bot.db import Card, Character, Database, User
from summon_bot.game import (
    daily_payout,
    hint_text,
    next_streak,
    normalize_name,
    parse_listing_price,
    pick_weighted,
    rarity_from_text,
    shop_price,
    spin_reward,
)
from summon_bot.repo import (
    buy_character,
    buy_listing,
    claim_daily,
    close_due_auctions,
    create_code,
    create_listing,
    get_or_create_user,
    give_card,
    open_auction,
    open_spawn,
    place_bid,
    redeem,
    try_claim,
)
from summon_bot.seed import seed
from summon_bot.webapp_auth import validate_init_data


def settings(tmp: Path) -> Settings:
    data = tmp / "data"
    data.mkdir(parents=True, exist_ok=True)
    return Settings(
        bot_token="123456:TEST",
        owner_id=1,
        owner_password="",
        database_url=f"sqlite+aiosqlite:///{tmp / 't.db'}",
        sqlite_path=tmp / "t.db",
        data_dir=data,
        api_id=0,
        api_hash="",
        session_string="",
        webhook_url="",
        webhook_secret="",
        webapp_url="",
        host="127.0.0.1",
        port=9,
        premium_chat_id=0,
        premium_star_price=75,
        vault_star_price=25,
        button_emoji_id="",
        spawn_seconds=90,
        spawn_every=100,
        starting_balance=500,
        daily_reward=5000,
        refresh_price=10000,
        hint_price=50,
        support_url="",
        log_channel_id=0,
        mongo_uri="",
        mongo_db_name="summon_bot",
        backup_interval_hours=12,
        backup_keep=14,
        inactive_days=90,
        maintenance_interval_hours=24,
        keepalive_url="",
        keepalive_seconds=300,
        heartbeat_minutes=0,
        tagall_limit=40,
        official_group_id=0,
        hclaim_cooldown_hours=24,
        market_pool_size=10,
        market_refresh_price=5000,
        market_sell_back_percent=50,
    )


class GameRulesTest(unittest.TestCase):
    def test_normalize_and_rarity(self):
        self.assertEqual(normalize_name("  Moon   Librarian! "), "moon librarian")
        self.assertEqual(rarity_from_text("Mythic Edition").key, "mythic")
        self.assertEqual(shop_price("rare", False), 25000)
        self.assertEqual(shop_price("rare", True), 22500)

    def test_weights_and_economy(self):
        self.assertEqual(pick_weighted([("a", 0), ("b", 5)], __import__("random").Random(1)), "b")
        self.assertEqual(next_streak(0, 0, 1000), 1)
        self.assertEqual(next_streak(1000, 3, 1000 + 24 * 3600), 4)
        self.assertEqual(next_streak(1000, 3, 1000 + 49 * 3600), 1)
        self.assertGreater(daily_payout(7, 5000), 5000)
        reward, lucky = spin_reward(6)
        self.assertTrue(lucky)
        self.assertGreater(reward, spin_reward(1)[0])
        self.assertEqual(parse_listing_price("15k"), 15000)
        self.assertIsNone(parse_listing_price("1"))
        self.assertIn("M", hint_text("Moon Librarian", "Stacks"))

    def test_database_url(self):
        url = normalize_database_url("postgres://user:pass@localhost/db", Path("x.db"))
        self.assertTrue(url.startswith("postgresql+asyncpg://"))
        self.assertTrue(normalize_database_url("", Path("x.db")).startswith("sqlite+aiosqlite://"))

    def test_keepalive_url(self):
        self.assertEqual(resolve_keepalive_url("https://host.example/ping", 8080), "https://host.example/ping")
        self.assertEqual(resolve_keepalive_url("https://host.example", 8080), "https://host.example/ping")
        saved = {key: os.environ.pop(key, None) for key in ("RENDER_EXTERNAL_URL", "RAILWAY_PUBLIC_DOMAIN")}
        try:
            self.assertEqual(resolve_keepalive_url("", 9000), "http://127.0.0.1:9000/ping")
            os.environ["RENDER_EXTERNAL_URL"] = "https://summon.onrender.com"
            self.assertEqual(resolve_keepalive_url("", 8080), "https://summon.onrender.com/ping")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_art(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "a.png"
            render_spawn(path, name_key="moon librarian", rarity_key="mythic")
            render_card(path, name="Moon Librarian", series="Stacks", rarity_key="mythic")
            self.assertGreater(path.stat().st_size, 1000)


class EconomyFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = settings(Path(self.tmp.name))
        self.db = Database(self.settings)
        await self.db.init()
        async with self.db.session() as session:
            await seed(session, self.settings)

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    def _user(self, user_id: int, balance: int = 500):
        return SimpleNamespace(id=user_id, username="u", first_name="U", is_bot=False)

    async def test_claim_shop_market_auction_and_code(self):
        async with self.db.session() as session:
            player = await get_or_create_user(session, self._user(10), self.settings)
            other = await get_or_create_user(session, self._user(11), self.settings)
            other.balance = 100_000
            player.balance = 100_000
            character = await session.scalar(select(Character).where(Character.name_key == "moon librarian"))
            await open_spawn(session, -100, character.id, 1, 60)
            wrong = await try_claim(session, -100, player, "tide warden")
            self.assertFalse(wrong.ok)
            caught = await try_claim(session, -100, player, "Moon Librarian!")
            self.assertTrue(caught.ok)
            self.assertEqual(player.claims, 1)
            again = await try_claim(session, -100, player, "moon librarian")
            self.assertEqual(again.reason, "none")

            status, card = await buy_character(session, player, character)
            self.assertEqual(status, "ok")
            poor = await session.get(User, player.id)
            poor.balance = 0
            status, _ = await buy_character(session, poor, character)
            self.assertEqual(status, "funds")
            poor.balance = 100_000

            listed, listing = await create_listing(session, player, card.id, 1500)
            self.assertEqual(listed, "ok")
            bought, price = await buy_listing(session, other, listing.id)
            self.assertEqual((bought, price), ("ok", 1500))
            moved = await session.get(Card, card.id)
            self.assertEqual(moved.user_id, other.id)

            gift_back = await give_card(session, player, character, "spawn")
            opened, auction = await open_auction(session, player, gift_back.id, 500, 1)
            self.assertEqual(opened, "ok")
            self.assertEqual(await place_bid(session, auction.id, other, 400), "low")
            self.assertEqual(await place_bid(session, auction.id, other, 800), "ok")
            self.assertEqual(other.balance, 100_000 - 1500 - 800)
            auction.ends_at = 1
            closed = await close_due_auctions(session)
            self.assertEqual(len(closed), 1)
            owned = await session.get(Card, gift_back.id)
            self.assertEqual(owned.user_id, other.id)
            seller = await session.get(User, player.id)
            self.assertGreaterEqual(seller.balance, 800)

            code = await create_code(session, 250, character.id, 1)
            status, note = await redeem(session, player, code.code.lower())
            self.assertEqual(status, "ok")
            self.assertIn("250", note)
            status, _ = await redeem(session, player, code.code)
            self.assertEqual(status, "used")

            state, payout, streak = await claim_daily(session, player, 5000)
            self.assertEqual(state, "ok")
            self.assertGreaterEqual(payout, 5000)
            self.assertEqual(streak, 1)
            state, _, _ = await claim_daily(session, player, 5000)
            self.assertEqual(state, "wait")


class InitDataTest(unittest.TestCase):
    def test_roundtrip(self):
        token = "123456:TEST"
        user = json.dumps({"id": 10, "first_name": "U"})
        pairs = {"auth_date": str(int(time.time())), "query_id": "abc", "user": user}
        check = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        digest = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        raw = urlencode({**pairs, "hash": digest})
        parsed = validate_init_data(raw, token)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["user"]["id"], 10)
        self.assertIsNone(validate_init_data(raw, "other:token"))


class ImportTest(unittest.IsolatedAsyncioTestCase):
    async def test_dispatcher_builds(self):
        from summon_bot.bot import build_dispatcher
        from summon_bot.bridge import KurigramBridge

        with tempfile.TemporaryDirectory() as raw:
            cfg = settings(Path(raw))
            database = Database(cfg)
            await database.init()
            dispatcher = build_dispatcher(cfg, database, KurigramBridge(cfg))
            self.assertIn("message", dispatcher.resolve_used_update_types())
            self.assertIn("purchased_paid_media", dispatcher.resolve_used_update_types())
            self.assertIn("guest_message", dispatcher.resolve_used_update_types())
            await database.close()


if __name__ == "__main__":
    unittest.main()
