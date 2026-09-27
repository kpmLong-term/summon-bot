"""Scheduled SQLite/Postgres-friendly backups into data/backups/."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings

log = logging.getLogger(__name__)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


async def run_backup(settings: Settings) -> Path | None:
    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    url = settings.database_url
    if url.startswith("sqlite"):
        src = settings.sqlite_path
        if not src.exists():
            return None
        dest = backup_dir / f"summon-{_stamp()}.db"
        await asyncio.to_thread(shutil.copy2, src, dest)
        _prune(backup_dir, settings.backup_keep)
        return dest
    if "postgresql" in url:
        dest = backup_dir / f"summon-{_stamp()}.sql"
        env = {"PGPASSWORD": _pg_password(url)}
        cmd = ["pg_dump", url.replace("postgresql+asyncpg://", "postgresql://"), "-f", str(dest)]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**dict(__import__("os").environ), **{k: v for k, v in env.items() if v}},
            )
            await proc.communicate()
            if proc.returncode != 0:
                log.warning("pg_dump failed with code %s", proc.returncode)
                return None
            _prune(backup_dir, settings.backup_keep)
            return dest
        except FileNotFoundError:
            log.warning("pg_dump not installed; skipping postgres backup")
            return None
    return None


def _pg_password(url: str) -> str:
    try:
        from urllib.parse import urlparse

        return urlparse(url.replace("+asyncpg", "")).password or ""
    except Exception:
        return ""


def _prune(folder: Path, keep: int) -> None:
    files = sorted(folder.glob("summon-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
