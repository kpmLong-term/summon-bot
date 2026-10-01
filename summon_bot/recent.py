"""Short memory of group message ids so admins can purge what the bot just saw."""

from __future__ import annotations

from collections import defaultdict, deque

_recent: dict[int, deque[int]] = defaultdict(lambda: deque(maxlen=25))


def remember(chat_id: int, message_id: int) -> None:
    _recent[chat_id].append(message_id)


def recent_ids(chat_id: int, limit: int) -> list[int]:
    items = list(_recent[chat_id])
    return items[-max(1, limit) :]


def forget(chat_id: int, message_ids: list[int]) -> None:
    drop = set(message_ids)
    kept = deque((item for item in _recent[chat_id] if item not in drop), maxlen=25)
    _recent[chat_id] = kept
