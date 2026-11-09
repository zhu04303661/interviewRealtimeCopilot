"""Small file helpers with owner-only permissions and atomic replacement."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any


def ensure_private_dir(path: Path) -> None:
    """Create ``path`` (and parents) readable only by the current user."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` so readers never see a partial file."""
    temporary = path.with_name(f"{path.name}.{secrets.token_hex(8)}")
    try:
        with open(temporary, "xb", opener=lambda p, flags: os.open(p, flags, 0o600)) as handle:
            handle.write(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: Any) -> None:
    """Serialise ``value`` compactly (as the JavaScript backend did) and write it atomically."""
    atomic_write_bytes(path, (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode())


def create_exclusive_json(path: Path, value: Any) -> None:
    """Write ``value`` to ``path`` only if no file exists there yet.

    The content is written to a temporary file first and then hard-linked into
    place, so a concurrent creator either sees the whole file or fails.
    """
    temporary = path.with_name(f".{secrets.token_hex(16)}")
    try:
        with open(temporary, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as handle:
            handle.write(json.dumps(value, separators=(",", ":")) + "\n")
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
