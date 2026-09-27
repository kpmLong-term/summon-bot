"""Inline keyboards using Bot API 9.4 button styles and optional custom emoji."""

from __future__ import annotations

from aiogram.types import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from .config import Settings
from .fonts import FONT_KEYS
from .game import RARITIES, SHOP_RARITIES


def _btn(
    settings: Settings,
    text: str,
    *,
    callback: str | None = None,
    url: str | None = None,
    web_app: str | None = None,
    copy: str | None = None,
    style: str | None = None,
) -> InlineKeyboardButton:
    kwargs: dict = {"text": text}
    if style:
        kwargs["style"] = style
    if settings.button_emoji_id:
        kwargs["icon_custom_emoji_id"] = settings.button_emoji_id
    if callback:
        kwargs["callback_data"] = callback
    elif url:
        kwargs["url"] = url
    elif web_app:
        kwargs["web_app"] = WebAppInfo(url=web_app)
    elif copy:
        kwargs["copy_text"] = CopyTextButton(text=copy)
    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        kwargs.pop("icon_custom_emoji_id", None)
        return InlineKeyboardButton(**kwargs)


def start_keyboard(settings: Settings, *, private: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            _btn(settings, "Collection", callback="col:0", style="primary"),
            _btn(settings, "Shop", callback="shop:open", style="success"),
        ],
        [
            _btn(settings, "Daily", callback="go:daily", style="primary"),
            _btn(settings, "Quests", callback="go:quests"),
        ],
        [
            _btn(settings, "Premium", callback="go:premium", style="success"),
            _btn(settings, "Help", callback="go:help"),
        ],
    ]
    if settings.webapp_url:
        if private:
            rows.append([_btn(settings, "Open album", web_app=f"{settings.webapp_url}/app/")])
        else:
            rows.append([_btn(settings, "Open album", url=f"{settings.webapp_url}/app/")])
    if settings.support_url:
        rows.append([_btn(settings, "Support", url=settings.support_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def help_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(settings, "Play", callback="help:play", style="primary"),
                _btn(settings, "Trade", callback="help:trade"),
            ],
            [
                _btn(settings, "Staff", callback="help:staff", style="danger"),
                _btn(settings, "Home", callback="go:home"),
            ]
        ]
    )


def shop_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    rows = []
    row: list[InlineKeyboardButton] = []
    for rarity in SHOP_RARITIES:
        row.append(_btn(settings, f"{rarity.emoji} {rarity.label.split()[0]}", callback=f"shop:r:{rarity.key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([_btn(settings, "Close", callback="go:home", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def offer_keyboard(settings: Settings, character_id: int, rarity: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(settings, "Buy", callback=f"shop:buy:{character_id}", style="success")],
            [
                _btn(settings, "Another", callback=f"shop:r:{rarity}", style="primary"),
                _btn(settings, "Rarities", callback="shop:open"),
            ],
        ]
    )


def collection_keyboard(settings: Settings, owner_id: int, page: int, pages: int) -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(_btn(settings, "Prev", callback=f"col:{owner_id}:{page - 1}"))
    nav.append(_btn(settings, f"{page + 1}/{max(pages, 1)}", callback="noop"))
    if page + 1 < pages:
        nav.append(_btn(settings, "Next", callback=f"col:{owner_id}:{page + 1}", style="primary"))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            nav,
            [
                _btn(settings, "Favorite this", callback=f"fav:{owner_id}:{page}", style="success"),
                _btn(settings, "Close", callback="go:home", style="danger"),
            ],
        ]
    )


def hint_keyboard(settings: Settings, chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn(settings, f"Hint ({settings.hint_price})", callback=f"hint:{chat_id}", style="primary")]]
    )


def hmode_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    rows = [[_btn(settings, "All", callback="hmode:all", style="primary")]]
    row: list[InlineKeyboardButton] = []
    for rarity in RARITIES:
        row.append(_btn(settings, rarity.emoji, callback=f"hmode:{rarity.key}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def font_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn(settings, key, callback=f"font:{key}", style="primary" if key == "plain" else None) for key in FONT_KEYS]]
    )


def top_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(settings, "Cards", callback="top:cards", style="primary"),
                _btn(settings, "Coins", callback="top:coins", style="success"),
            ]
        ]
    )


def market_keyboard(settings: Settings, listing_ids: list[int], page: int) -> InlineKeyboardMarkup:
    rows = [[_btn(settings, f"Buy #{listing_id}", callback=f"mkt:{listing_id}", style="success")] for listing_id in listing_ids]
    nav = []
    if page > 0:
        nav.append(_btn(settings, "Prev", callback=f"mktpage:{page - 1}"))
    nav.append(_btn(settings, "Next", callback=f"mktpage:{page + 1}", style="primary"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_keyboard(settings: Settings, yes: str, no: str = "go:home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            _btn(settings, "Confirm", callback=yes, style="danger"),
            _btn(settings, "Cancel", callback=no),
        ]]
    )


def quest_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(settings, "Catch reward", callback="quest:catch", style="success"),
                _btn(settings, "Chat reward", callback="quest:msgs"),
            ],
            [_btn(settings, "Daily reward", callback="quest:daily", style="primary")],
        ]
    )


def owner_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(settings, "Star balance", callback="op:stars", style="primary"),
                _btn(settings, "Counts", callback="op:counts"),
            ],
            [
                _btn(settings, "Subscription link", callback="op:sublink"),
                _btn(settings, "Restart", callback="op:restart", style="danger"),
            ],
        ]
    )


def copy_keyboard(settings: Settings, value: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(settings, "Copy code", copy=value, style="primary")]])


def private_menu(settings: Settings) -> ReplyKeyboardMarkup | None:
    if not settings.webapp_url:
        return None
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Album", web_app=WebAppInfo(url=f"{settings.webapp_url}/app/"), style="primary")]],
        resize_keyboard=True,
    )
