"""Unicode name styles. No bundled font files."""

from __future__ import annotations

_BOLD = {ord(ch): 0x1D5D4 + (ord(ch) - 65) for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
_BOLD.update({ord(ch): 0x1D5EE + (ord(ch) - 97) for ch in "abcdefghijklmnopqrstuvwxyz"})
_BOLD.update({ord(str(n)): 0x1D7EC + n for n in range(10)})

_MONO = {ord(ch): 0x1D670 + (ord(ch) - 65) for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
_MONO.update({ord(ch): 0x1D68A + (ord(ch) - 97) for ch in "abcdefghijklmnopqrstuvwxyz"})
_MONO.update({ord(str(n)): 0x1D7F6 + n for n in range(10)})

_SMALL = {
    "a": "ᴀ",
    "b": "ʙ",
    "c": "ᴄ",
    "d": "ᴅ",
    "e": "ᴇ",
    "f": "ꜰ",
    "g": "ɢ",
    "h": "ʜ",
    "i": "ɪ",
    "j": "ᴊ",
    "k": "ᴋ",
    "l": "ʟ",
    "m": "ᴍ",
    "n": "ɴ",
    "o": "ᴏ",
    "p": "ᴘ",
    "q": "ǫ",
    "r": "ʀ",
    "s": "ꜱ",
    "t": "ᴛ",
    "u": "ᴜ",
    "v": "ᴠ",
    "w": "ᴡ",
    "x": "x",
    "y": "ʏ",
    "z": "ᴢ",
}

FONT_KEYS = ("plain", "bold", "mono", "small")


def apply_font(text: str, font: str) -> str:
    if font == "bold":
        return text.translate(_BOLD)
    if font == "mono":
        return text.translate(_MONO)
    if font == "small":
        return "".join(_SMALL.get(ch, ch) for ch in text.casefold()) if text else text
    return text
