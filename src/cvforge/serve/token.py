"""The pairing token the extension sends in X-CVForge-Token."""
from __future__ import annotations

import os
import secrets
from pathlib import Path


def load_or_create(data_dir: Path) -> str:
    path = Path(data_dir) / "serve" / "token"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value + "\n")
    os.chmod(path, 0o600)
    return value
