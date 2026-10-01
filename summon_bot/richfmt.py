"""Rich message HTML via richgram (Badmunda05), sent by Aiogram."""

from __future__ import annotations

from richgram import rich_esc, rich_footer, rich_heading, rich_kv_table, rich_note


def log_html(event: str, detail: str, stamp: str) -> str:
    rows = [("When", f"<code>{rich_esc(stamp)}</code>")]
    if detail:
        rows.insert(0, ("Detail", rich_esc(detail)))
    return (
        rich_heading(rich_esc(event), 3)
        + rich_kv_table(rows)
        + rich_note("Summon log")
        + rich_footer("Built with richgram")
    )


def welcome_html(name: str, help_html: str) -> str:
    return (
        rich_heading(f"Welcome, {name}", 2)
        + rich_note("Characters spawn in groups. Guess the name, keep the card, trade the spare.")
        + help_html
    )
