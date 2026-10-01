"""Dispatcher, command menu, and process entry."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllChatAdministrators, BotCommandScopeAllGroupChats, BotCommandScopeDefault, ErrorEvent, LinkPreviewOptions

from .audit import audit, close_mongo, init_mongo
from .bridge import KurigramBridge
from .config import Settings
from .db import Database
from .handlers import build_router
from .http import build_web_app
from .middleware import DbMiddleware
from .repo import close_due_auctions
from .seed import seed
from .watchdog import backup_loop, heartbeat_loop, keepalive_loop, maintenance_loop

log = logging.getLogger(__name__)

PLAYER_COMMANDS = [
    BotCommand(command="start", description="Open the menu"),
    BotCommand(command="help", description="How to play"),
    BotCommand(command="collection", description="Browse your cards", is_ephemeral=True),
    BotCommand(command="profile", description="Your profile", is_ephemeral=True),
    BotCommand(command="balance", description="Coin balance", is_ephemeral=True),
    BotCommand(command="daily", description="Claim the daily", is_ephemeral=True),
    BotCommand(command="spin", description="Roll the dice"),
    BotCommand(command="shop", description="Buy a character", is_ephemeral=True),
    BotCommand(command="market", description="Browse listings", is_ephemeral=True),
    BotCommand(command="sell", description="List a card"),
    BotCommand(command="auction", description="Start an auction"),
    BotCommand(command="bid", description="Bid on an auction"),
    BotCommand(command="gift", description="Give a card"),
    BotCommand(command="pay", description="Send coins"),
    BotCommand(command="search", description="Find a name", is_ephemeral=True),
    BotCommand(command="check", description="Inspect a card or name", is_ephemeral=True),
    BotCommand(command="top", description="Leaderboard", is_ephemeral=True),
    BotCommand(command="quests", description="Daily goals", is_ephemeral=True),
    BotCommand(command="nguess", description="Name quiz"),
    BotCommand(command="premium", description="Buy premium with Stars"),
    BotCommand(command="vault", description="Legendary paid pull"),
    BotCommand(command="redeem", description="Redeem a code", is_ephemeral=True),
]

GROUP_COMMANDS = [
    BotCommand(command="hclaim", description="Daily weighted claim"),
    BotCommand(command="claimlist", description="Hclaim weight list", is_ephemeral=True),
    BotCommand(command="hstats", description="Detailed stats", is_ephemeral=True),
    BotCommand(command="nguess", description="Name quiz"),
    BotCommand(command="nguess_end", description="Close open quizzes"),
    BotCommand(command="auctionlist", description="Open auctions", is_ephemeral=True),
    BotCommand(command="mybids", description="Your bids", is_ephemeral=True),
    BotCommand(command="inv", description="Inventory", is_ephemeral=True),
    BotCommand(command="spawn", description="Force the next spawn"),
    BotCommand(command="checkspawn", description="Spawn progress", is_ephemeral=True),
    BotCommand(command="claimlist", description="Active spawn timer", is_ephemeral=True),
    BotCommand(command="changetime", description="Messages between spawns"),
    BotCommand(command="chance", description="Set a rarity weight"),
    BotCommand(command="savegroup", description="Register this group"),
    *PLAYER_COMMANDS,
]

ADMIN_COMMANDS = [
    BotCommand(command="setclaim", description="Set hclaim weight"),
    BotCommand(command="remove", description="Remove user character"),
    BotCommand(command="cshop000000", description="Rotating market pool"),
    BotCommand(command="cancelauction", description="Cancel your auction"),
    BotCommand(command="pinfo", description="Premium info", is_ephemeral=True),
    BotCommand(command="unpremium", description="Strip premium"),
    BotCommand(command="backup", description="Backup database now", is_ephemeral=True),
    BotCommand(command="ban", description="Ban a replied user"),
    BotCommand(command="unban", description="Unban a user"),
    BotCommand(command="tagall", description="Mention tracked members"),
    BotCommand(command="kick", description="Kick a replied user"),
    BotCommand(command="pin", description="Pin a replied message"),
    BotCommand(command="warn", description="Warn a replied user"),
    BotCommand(command="addchar", description="Add a character from a photo"),
    BotCommand(command="sudolist", description="List sudo", is_ephemeral=True),
    *GROUP_COMMANDS,
]


def build_dispatcher(settings: Settings, database: Database, bridge: KurigramBridge) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.workflow_data.update(settings=settings, bridge=bridge, database=database)
    dispatcher.update.outer_middleware(DbMiddleware(database, settings))
    dispatcher.include_router(build_router())

    @dispatcher.errors()
    async def on_error(event: ErrorEvent) -> bool:
        exc = event.exception
        if isinstance(exc, TelegramBadRequest) and "message is not modified" in str(exc).lower():
            return True
        log.exception("update failed", exc_info=exc)
        return True

    return dispatcher


def _unique(commands: list[BotCommand]) -> list[BotCommand]:
    seen: set[str] = set()
    chosen: list[BotCommand] = []
    for command in commands:
        if command.command in seen:
            continue
        seen.add(command.command)
        chosen.append(command)
    return chosen[:100]


async def setup_commands(bot: Bot) -> None:
    await bot.set_my_commands(_unique(PLAYER_COMMANDS), scope=BotCommandScopeDefault())
    await bot.set_my_commands(_unique(GROUP_COMMANDS), scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(_unique(ADMIN_COMMANDS), scope=BotCommandScopeAllChatAdministrators())


async def _auctions(bot: Bot, database: Database) -> None:
    while True:
        await asyncio.sleep(20)
        try:
            async with database.session() as session:
                closed = await close_due_auctions(session)
            for auction in closed:
                text = f"Auction #{auction.id} closed."
                if auction.bidder_id:
                    text = f"Auction #{auction.id} sold card #{auction.card_id} for {auction.current_bid}."
                for chat_id in {auction.seller_id, auction.bidder_id}:
                    if not chat_id:
                        continue
                    try:
                        await bot.send_message(chat_id, text)
                    except Exception:
                        continue
        except Exception:
            log.exception("auction closer failed")


async def run(settings: Settings | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or Settings.load()
    if not settings.bot_token:
        raise SystemExit("Set BOT_TOKEN in the environment or .env file.")
    database = Database(settings)
    await database.init()
    await init_mongo(settings)
    async with database.session() as session:
        created = await seed(session, settings)
    log.info("seed created %s characters", created)
    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview=LinkPreviewOptions(is_disabled=True)),
    )
    bridge = KurigramBridge(settings)
    dispatcher = build_dispatcher(settings, database, bridge)
    await bridge.start()
    site_runner = None
    auction_task = asyncio.create_task(_auctions(bot, database))
    bg_tasks = [
        asyncio.create_task(keepalive_loop(settings)),
        asyncio.create_task(backup_loop(bot, settings, database)),
        asyncio.create_task(maintenance_loop(bot, settings, database)),
    ]
    if settings.heartbeat_minutes > 0 and settings.log_channel_id:
        bg_tasks.append(asyncio.create_task(heartbeat_loop(bot, settings)))
    try:
        from aiohttp import web

        web_app = build_web_app(
            settings,
            database,
            bot if settings.webhook_url else None,
            dispatcher if settings.webhook_url else None,
        )
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, settings.host, settings.port)
        await site.start()
        site_runner = runner
        log.info("http listening on %s:%s", settings.host, settings.port)
        log.info("Watchdog started (backup, inactive cleanup, keep-alive)")
        if settings.webhook_url:
            await bot.set_webhook(
                f"{settings.webhook_url}/webhook",
                secret_token=settings.webhook_secret or None,
                allowed_updates=dispatcher.resolve_used_update_types(),
                drop_pending_updates=False,
            )
            await setup_commands(bot)
            await audit(bot, settings, "Online", f"Webhook · {settings.database_backend}")
            await asyncio.Event().wait()
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            await setup_commands(bot)
            await audit(bot, settings, "Online", f"Polling · {settings.database_backend}")
            await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        for task in bg_tasks:
            task.cancel()
        auction_task.cancel()
        await close_mongo()
        await bridge.stop()
        if site_runner is not None:
            await site_runner.cleanup()
        await bot.session.close()
        await database.close()
