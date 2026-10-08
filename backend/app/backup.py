"""Instance backup and restore (ADM-6), from the command line only: the operator's tool, not an admin's.

A backup is one .tar.gz: the SQLite database (copied with SQLite's online backup API, so it's consistent while the
app runs), the uploaded files, and a manifest. With PostgreSQL the database is left to pg_dump, and the archive
holds the uploads. API keys and two-step secrets in the database stay encrypted: a backup is useless without
APP_SECRET_KEY, which is never in it. Keep the two apart.

Restore expects the app to be stopped. It keeps what it replaces next to the originals ("...before-restore-<time>"),
then brings the restored database up to the current schema.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from app.config import Settings
from app.db.engine import run_migrations

FORMAT = 1


class BackupError(Exception):
    pass


def _sqlite_path(settings: Settings) -> Path:
    return Path(settings.db_url_sync.removeprefix("sqlite:///"))


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def backup(settings: Settings, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"resume-tailor-backup-{_stamp()}.tar.gz"
    uploads = settings.data_dir / "uploads"
    with tempfile.TemporaryDirectory(dir=settings.data_dir) as work:
        manifest = {"format": FORMAT, "createdAt": datetime.now(UTC).isoformat(),
                    "database": "sqlite" if settings.is_sqlite else "postgresql"}
        db_copy = Path(work) / "app.db"
        if settings.is_sqlite:
            source = sqlite3.connect(_sqlite_path(settings))
            dest = sqlite3.connect(db_copy)
            try:
                source.backup(dest)  # a consistent copy, even while the app writes
            finally:
                dest.close()
                source.close()
        (Path(work) / "manifest.json").write_text(json.dumps(manifest, indent=2))
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # private: it holds every account's data
        with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as archive:
            archive.add(Path(work) / "manifest.json", arcname="manifest.json")
            if settings.is_sqlite:
                archive.add(db_copy, arcname="app.db")
            if uploads.is_dir():
                archive.add(uploads, arcname="uploads")
    return target


def _check_members(archive: tarfile.TarFile) -> None:
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        top = path.parts[0] if path.parts else ""
        if path.is_absolute() or ".." in path.parts or top not in ("manifest.json", "app.db", "uploads"):
            raise BackupError(f"unexpected entry in the archive: {member.name!r}")
        if not (member.isfile() or member.isdir()):
            raise BackupError(f"links and devices aren't allowed in a backup: {member.name!r}")


def restore(settings: Settings, archive_path: Path) -> list[str]:
    """Replace the database and uploads with the backup's; returns what was done, line by line."""
    done: list[str] = []
    with tempfile.TemporaryDirectory(dir=settings.data_dir) as work:
        with tarfile.open(archive_path, "r:gz") as archive:
            _check_members(archive)
            archive.extractall(work, filter="data")
        manifest_path = Path(work) / "manifest.json"
        if not manifest_path.is_file():
            raise BackupError("this isn't a Resume Tailor backup (no manifest)")
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("format") != FORMAT:
            raise BackupError(f"unsupported backup format: {manifest.get('format')!r}")
        stamp = _stamp()
        restored_db = Path(work) / "app.db"
        if restored_db.is_file():
            if not settings.is_sqlite:
                raise BackupError("this backup holds a SQLite database, but this instance uses PostgreSQL")
            db_path = _sqlite_path(settings)
            if db_path.exists():
                kept = db_path.with_name(f"{db_path.name}.before-restore-{stamp}")
                db_path.rename(kept)
                done.append(f"kept the previous database as {kept}")
            for suffix in ("-wal", "-shm"):  # belong to the old database
                Path(f"{db_path}{suffix}").unlink(missing_ok=True)
            shutil.move(restored_db, db_path)
            done.append(f"restored the database ({manifest.get('createdAt')})")
        elif manifest.get("database") == "postgresql":
            done.append("the database isn't in this backup: restore PostgreSQL from your pg_dump")
        uploads = settings.data_dir / "uploads"
        restored_uploads = Path(work) / "uploads"
        if uploads.exists():
            kept = uploads.with_name(f"uploads.before-restore-{stamp}")
            uploads.rename(kept)
            done.append(f"kept the previous uploads as {kept}")
        if restored_uploads.is_dir():
            shutil.move(restored_uploads, uploads)
            done.append("restored the uploaded files")
    if settings.is_sqlite:
        run_migrations(settings.db_url_sync)
        done.append("brought the database up to the current schema")
    return done
