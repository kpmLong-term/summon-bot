"""Original cast. Admins can add their own photos with /addchar."""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .art import render_card, render_spawn
from .config import Settings
from .db import Character, Weight
from .game import RARITIES, normalize_name

CAST: tuple[tuple[str, str, str], ...] = (
    ("Pebble Scout", "Road Lanterns", "common"),
    ("Lantern Moth", "Road Lanterns", "common"),
    ("Brook Finch", "River Mile", "common"),
    ("Copper Imp", "River Mile", "common"),
    ("Velvet Fox", "Glass Market", "rare"),
    ("Tide Warden", "Glass Market", "rare"),
    ("Amber Knight", "Cinder Court", "rare"),
    ("Glass Owl", "Cinder Court", "rare"),
    ("Moon Librarian", "Night Stacks", "special"),
    ("Storm Piper", "Night Stacks", "special"),
    ("Silk Oracle", "Night Stacks", "special"),
    ("Crown of Embers", "Cinder Court", "legendary"),
    ("Night Admiral", "Black Harbor", "legendary"),
    ("Solar Hart", "Daybreak", "legendary"),
    ("Eclipse Saint", "Daybreak", "mythic"),
    ("Void Gardener", "Black Harbor", "mythic"),
    ("Heart Smith", "Festival Week", "valentine"),
    ("Tide Dancer", "Festival Week", "summer"),
    ("Lantern Reaper", "Festival Week", "halloween"),
    ("Snow Warden", "Festival Week", "christmas"),
    ("Star Cartographer", "High Arc", "celestial"),
    ("Last Witness", "High Arc", "limited"),
)


async def seed(session: AsyncSession, settings: Settings) -> int:
    existing = set((await session.scalars(select(Character.name_key))).all())
    created = 0
    for name, series, rarity in CAST:
        key = normalize_name(name)
        if key in existing:
            continue
        session.add(Character(name=name, name_key=key, series=series, rarity=rarity, catch_count=0))
        created += 1
    weight_rows = (await session.scalars(select(func.count()).select_from(Weight).where(Weight.chat_id == 0))).one()
    if weight_rows == 0:
        for rarity in RARITIES:
            session.add(Weight(chat_id=0, rarity=rarity.key, weight=rarity.weight))
    await session.flush()
    characters = (await session.scalars(select(Character))).all()
    art_dir = settings.data_dir / "art"

    def _render_all() -> None:
        for character in characters:
            if character.custom_path:
                continue
            render_spawn(art_dir / f"{character.id}_spawn.png", name_key=character.name_key, rarity_key=character.rarity)
            render_card(
                art_dir / f"{character.id}_card.png",
                name=character.name,
                series=character.series,
                rarity_key=character.rarity,
            )

    await asyncio.to_thread(_render_all)
    return created
