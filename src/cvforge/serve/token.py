"""The pairing token the extension sends in X-CVForge-Token."""
from __future__ import annotations

import os
import secrets
from pathlib import Path


def load_or_create(data_dir: Path) -> str:
    """Reuse the token if there is one, else make it. Either way only the owner can read it."""
    path = Path(data_dir) / "serve" / "token"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            os.chmod(path.parent, 0o700)
            os.chmod(path, 0o600)
            return value
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    value = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value + "\n")
    os.chmod(path, 0o600)
    return value
