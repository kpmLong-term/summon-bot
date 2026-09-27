"""Pure game rules. No Telegram and no database imports."""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Rarity:
    key: str
    label: str
    emoji: str
    price: int
    weight: int
    shop: bool = True


RARITIES: tuple[Rarity, ...] = (
    Rarity("common", "Common", "⚪", 15_000, 46),
    Rarity("rare", "Rare", "🔵", 25_000, 25),
    Rarity("special", "Special Edition", "💮", 50_000, 12),
    Rarity("legendary", "Legendary", "⭐", 90_000, 8),
    Rarity("mythic", "Mythic Edition", "🛸", 150_000, 4),
    Rarity("valentine", "Valentine Edition", "💝", 250_000, 1, shop=False),
    Rarity("summer", "Summer Edition", "🏖️", 250_000, 1, shop=False),
    Rarity("halloween", "Halloween Edition", "🎃", 350_000, 1, shop=False),
    Rarity("christmas", "Christmas Edition", "🎄", 350_000, 1, shop=False),
    Rarity("celestial", "Celestial Edition", "🌌", 1_000_000, 1, shop=False),
    Rarity("limited", "Limited Edition", "🔮", 2_000_000, 1, shop=False),
)

RARITY_BY_KEY = {item.key: item for item in RARITIES}
SHOP_RARITIES = tuple(item for item in RARITIES if item.shop)

STREAK_BONUS = ((30, 15_000), (14, 5_000), (7, 2_000), (3, 500))
SPIN_COOLDOWN = 24 * 60 * 60
DAILY_COOLDOWN = 24 * 60 * 60
STREAK_GRACE = 48 * 60 * 60
PREMIUM_SECONDS = 30 * 24 * 60 * 60
MIN_LISTING_PRICE = 100
MAX_LISTING_PRICE = 1_000_000_000_000
SPAM_WARN = 20
SPAM_BAN = 40

ACHIEVEMENTS: tuple[tuple[str, str], ...] = (
    ("first_catch", "First catch"),
    ("catch_10", "Ten catches"),
    ("catch_50", "Fifty catches"),
    ("streak_7", "Week streak"),
    ("rich", "100k purse"),
    ("mythic", "Mythic keeper"),
    ("premium", "Star patron"),
)


def now_ts() -> int:
    return int(time.time())


def normalize_name(value: str) -> str:
    cleaned = "".join(ch for ch in value.casefold().strip() if ch.isalnum() or ch.isspace())
    return " ".join(cleaned.split())


def rarity_from_text(value: str) -> Rarity | None:
    key = normalize_name(value).replace(" ", "")
    aliases = {
        "common": "common",
        "rare": "rare",
        "special": "special",
        "specialedition": "special",
        "legendary": "legendary",
        "mythic": "mythic",
        "mythicedition": "mythic",
        "valentine": "valentine",
        "valentineedition": "valentine",
        "summer": "summer",
        "summeredition": "summer",
        "halloween": "halloween",
        "halloweenedition": "halloween",
        "christmas": "christmas",
        "christmasedition": "christmas",
        "celestial": "celestial",
        "celestialedition": "celestial",
        "limited": "limited",
        "limitededition": "limited",
    }
    found = aliases.get(key)
    if found:
        return RARITY_BY_KEY[found]
    for item in RARITIES:
        if normalize_name(item.label) == normalize_name(value):
            return item
    return None


def pick_weighted(weights: list[tuple[str, int]], rng: random.Random | None = None) -> str:
    bag = [(key, weight) for key, weight in weights if weight > 0]
    if not bag:
        raise ValueError("no positive weights")
    roll = (rng or random.Random()).randrange(sum(weight for _, weight in bag))
    cursor = 0
    for key, weight in bag:
        cursor += weight
        if roll < cursor:
            return key
    return bag[-1][0]


def shop_price(rarity_key: str, premium: bool) -> int:
    rarity = RARITY_BY_KEY[rarity_key]
    if premium:
        return max(1, rarity.price * 90 // 100)
    return rarity.price


def streak_bonus(streak: int) -> int:
    for days, bonus in STREAK_BONUS:
        if streak >= days:
            return bonus
    return 0


def daily_payout(streak: int, base: int) -> int:
    return base + streak_bonus(streak)


def next_streak(previous_claim_at: int, current_streak: int, moment: int | None = None) -> int:
    moment = now_ts() if moment is None else moment
    if previous_claim_at <= 0:
        return 1
    gap = moment - previous_claim_at
    if gap < DAILY_COOLDOWN:
        return current_streak
    if gap <= STREAK_GRACE:
        return current_streak + 1
    return 1


def spin_reward(dice_value: int) -> tuple[int, bool]:
    value = min(6, max(1, dice_value))
    reward = 100 + (value - 1) * 180
    lucky = value == 6
    if lucky:
        reward += 2000
    return reward, lucky


def achievement_keys(
    *,
    claims: int,
    best_streak: int,
    balance: int,
    owned_rarities: set[str],
    premium: bool,
) -> set[str]:
    unlocked: set[str] = set()
    if claims >= 1:
        unlocked.add("first_catch")
    if claims >= 10:
        unlocked.add("catch_10")
    if claims >= 50:
        unlocked.add("catch_50")
    if best_streak >= 7:
        unlocked.add("streak_7")
    if balance >= 100_000:
        unlocked.add("rich")
    if "mythic" in owned_rarities or "limited" in owned_rarities or "celestial" in owned_rarities:
        unlocked.add("mythic")
    if premium:
        unlocked.add("premium")
    return unlocked


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def parse_listing_price(raw: str) -> int | None:
    text = raw.strip().lower().replace(",", "")
    match = re.fullmatch(r"(\d+)([kmb])?", text)
    if not match:
        return None
    value = int(match.group(1))
    mult = {None: 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[match.group(2)]
    value *= mult
    if value < MIN_LISTING_PRICE or value > MAX_LISTING_PRICE:
        return None
    return value


def hint_text(name: str, series: str) -> str:
    parts = name.split()
    masked = " ".join((word[0] + "•" * (len(word) - 1)) if word else "" for word in parts)
    series_bit = f" Series: {series}." if series else ""
    return f"Hint: {masked}.{series_bit}"
