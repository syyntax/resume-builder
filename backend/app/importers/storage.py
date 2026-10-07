"""Uploaded files on disk: ``DATA_DIR/uploads/<owner id>/<random>``, outside anything web-served (§10.5).

Rows in ``uploaded_file`` hold the metadata; the API only ever reaches a file through its owner-scoped
row, so the storage key never comes from a request.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
from pathlib import Path


class FileStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("storage key outside the upload directory")
        return path

    def save(self, owner_id: str, data: bytes) -> str:
        folder = self.root / owner_id
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = f"{owner_id}/{secrets.token_hex(16)}"
        fd = os.open(self._path(key), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        return key

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path(key).unlink()

    def delete_owner(self, owner_id: str) -> None:
        folder = self.root / owner_id
        if folder.resolve().parent == self.root.resolve():
            shutil.rmtree(folder, ignore_errors=True)
