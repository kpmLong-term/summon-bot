"""Router registration."""

from aiogram import Router

from .extras import router as extras_router
from .manage import router as manage_router
from .platform import router as platform_router
from .play import router as play_router
from .staff import router as staff_router
from .trade import router as trade_router


def build_router() -> Router:
    root = Router()
    root.include_router(play_router)
    root.include_router(trade_router)
    root.include_router(extras_router)
    root.include_router(staff_router)
    root.include_router(manage_router)
    root.include_router(platform_router)
    return root
