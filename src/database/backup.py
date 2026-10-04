"""Database backups: online SQLite snapshot before every pipeline run.

Uses the SQLite online-backup API (safe against concurrent readers and
the WAL), stores timestamped copies in backups/, keeps the newest N.
Best-effort everywhere: a failed backup logs and never breaks a run.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BACKUP_KEEP_DEFAULT = 14


def backup_dir() -> Path:
    from src.database.db import DB_PATH

    path = Path(DB_PATH).parent / "backups"
    path.mkdir(exist_ok=True)
    return path


def backup_database(keep: int = BACKUP_KEEP_DEFAULT) -> str | None:
    """Snapshot the live DB. Returns the backup path, or None on failure."""
    from src.database.db import DB_PATH

    try:
        dest = backup_dir() / f"leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(dest)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        _prune(keep)
        logger.info("Database backed up to %s", dest)
        return str(dest)
    except Exception as exc:
        logger.warning("Database backup failed: %s", exc)
        return None


def _prune(keep: int) -> None:
    try:
        files = sorted(
            (p for p in backup_dir().glob("leads_*.db") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        for old in files[: -max(keep, 1)] if len(files) > keep else []:
            try:
                old.unlink()
            except OSError:
                pass
    except Exception as exc:
        logger.debug("Backup prune failed: %s", exc)


def list_backups(limit: int = 8) -> list[dict]:
    """Newest backups first (name, size_kb, modified). Never raises."""
    try:
        files = sorted(
            (p for p in backup_dir().glob("leads_*.db") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return [
            {
                "name": p.name,
                "size_kb": round(p.stat().st_size / 1024, 1),
                "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M"
                ),
            }
            for p in files[:limit]
        ]
    except Exception:
        return []
