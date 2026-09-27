"""Generated spawn art and catch cards. Original patterns, no external images."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .game import RARITY_BY_KEY


def _palette(seed: str) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    digest = hashlib.sha256(seed.encode()).digest()
    return (
        (30 + digest[0] % 60, 24 + digest[1] % 50, 40 + digest[2] % 80),
        (80 + digest[3] % 160, 70 + digest[4] % 150, 90 + digest[5] % 150),
        (220, 210, 190),
    )


def _font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def render_spawn(path: Path, *, name_key: str, rarity_key: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rarity = RARITY_BY_KEY[rarity_key]
    base, accent, ink = _palette(name_key)
    image = Image.new("RGB", (720, 420), base)
    draw = ImageDraw.Draw(image)
    for i in range(18):
        y = 20 + i * 22
        color = tuple(min(255, channel + i * 4) for channel in accent)
        draw.arc((40 - i * 6, y - 80, 680 + i * 6, y + 160), 200, 340, fill=color, width=3)
    draw.rounded_rectangle((36, 36, 684, 384), radius=28, outline=accent, width=6)
    draw.text((70, 70), rarity.emoji, font=_font(64), fill=ink)
    draw.text((70, 250), rarity.label.upper(), font=_font(36), fill=ink)
    draw.text((70, 310), "WHO IS THIS?", font=_font(28), fill=accent)
    image.save(path, format="PNG")
    return path


def render_card(path: Path, *, name: str, series: str, rarity_key: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rarity = RARITY_BY_KEY[rarity_key]
    base, accent, ink = _palette(name.casefold())
    image = Image.new("RGB", (720, 900), base)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 720, 220), fill=accent)
    draw.rounded_rectangle((48, 180, 672, 840), radius=32, fill=(18, 16, 24))
    draw.text((72, 60), f"{rarity.emoji}  {rarity.label}", font=_font(32), fill=(20, 16, 24))
    draw.text((80, 240), name[:28], font=_font(42), fill=ink)
    draw.text((80, 310), series[:40] or "Original", font=_font(28), fill=accent)
    draw.text((80, 760), "SUMMON", font=_font(24), fill=accent)
    image.save(path, format="PNG")
    return path
