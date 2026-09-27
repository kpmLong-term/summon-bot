"""Health check, Mini App static files, and optional webhook."""

from __future__ import annotations

import json
import time
from pathlib import Path

from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .db import Card, Character, Database, User
from .game import RARITY_BY_KEY
from .webapp_auth import validate_init_data

APP_DIR = Path(__file__).resolve().parent / "web"
_started = time.time()


def build_web_app(settings: Settings, database: Database, bot=None, dispatcher=None) -> web.Application:
    app = web.Application()
    app["settings"] = settings
    app["database"] = database
    app.router.add_get("/health", health)
    app.router.add_get("/ping", ping)
    app.router.add_get("/app/", mini_app)
    app.router.add_get("/app/static/{name}", static_file)
    app.router.add_get("/app/api/collection", collection_api)
    if bot is not None and dispatcher is not None and settings.webhook_url:
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

        SimpleRequestHandler(dispatcher=dispatcher, bot=bot, secret_token=settings.webhook_secret or None).register(
            app, path="/webhook"
        )
        setup_application(app, dispatcher, bot=bot)
    return app


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "uptime": int(time.time() - _started)})


async def ping(_request: web.Request) -> web.Response:
    return web.Response(text="pong")


async def mini_app(_request: web.Request) -> web.Response:
    return web.FileResponse(APP_DIR / "index.html")


async def static_file(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    if ".." in name or "/" in name:
        raise web.HTTPNotFound()
    path = APP_DIR / "static" / name
    if not path.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(path)


async def collection_api(request: web.Request) -> web.Response:
    settings: Settings = request.app["settings"]
    database: Database = request.app["database"]
    header = request.headers.get("Authorization", "")
    init_data = header[4:].strip() if header.startswith("tma ") else header.removeprefix("tma ").strip()
    parsed = validate_init_data(init_data, settings.bot_token)
    if not parsed or not isinstance(parsed.get("user"), dict):
        return web.json_response({"error": "unauthorized"}, status=401)
    user_id = int(parsed["user"]["id"])
    async with database.session() as session:
        payload = await _collection_payload(session, user_id)
    if payload is None:
        return web.json_response({"error": "start the bot first"}, status=404)
    return web.json_response(payload)


async def _collection_payload(session: AsyncSession, user_id: int) -> dict | None:
    user = await session.get(User, user_id)
    if user is None:
        return None
    rows = (
        await session.execute(
            select(Card, Character)
            .join(Character, Character.id == Card.character_id)
            .where(Card.user_id == user_id)
            .order_by(Card.id.desc())
            .limit(60)
        )
    ).all()
    cards = []
    for card, character in rows:
        rarity = RARITY_BY_KEY.get(character.rarity)
        cards.append(
            {
                "id": card.id,
                "name": character.name,
                "series": character.series,
                "rarity": rarity.label if rarity else character.rarity,
                "emoji": rarity.emoji if rarity else "",
                "key": character.rarity,
            }
        )
    return {
        "name": user.first_name,
        "balance": user.balance,
        "claims": user.claims,
        "cards": cards,
    }
