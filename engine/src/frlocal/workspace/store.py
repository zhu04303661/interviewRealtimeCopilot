"""Loading, locking and saving one account's ``workspace.json``.

Every operation runs under that account's lock and reloads the file, so the
state on disk is the single source of truth and concurrent requests never
interleave half-applied changes. Writes happen only when an operation marks
the state as changed.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from ..errors import fail
from ..fileio import atomic_write_bytes, atomic_write_json, ensure_private_dir

ACCOUNT_NAME = re.compile(r"^[a-z][a-z0-9._-]{2,31}$")
OBJECT_ID = re.compile(r"^[0-9a-f-]{36}$")

DEFAULT_PREFS = {"default_playbook_id": None, "language": None, "coding_language": None}
DEFAULT_CONSENTS = {"share_data": False, "ai_training": False}


def migrate_legacy_workspaces(legacy: Path | None, target: Path) -> list[str]:
    """Copy account workspaces from an older location into ``target``.

    Earlier builds kept workspaces inside the app's profile folder, next to the
    app bundle. They now live in a stable folder that rebuilds never touch. An
    account is copied only if it has no workspace in ``target`` yet; the old
    folder is left as it is, as a backup. Returns the accounts copied.
    """
    if not legacy or not legacy.is_dir() or legacy.resolve() == target.resolve():
        return []
    copied = []
    for account in sorted(legacy.iterdir()):
        source = account / "workspace.json"
        if not ACCOUNT_NAME.match(account.name) or not source.is_file() or (target / account.name / "workspace.json").exists():
            continue
        ensure_private_dir(target)
        shutil.copytree(account, target / account.name, dirs_exist_ok=True)
        copied.append(account.name)
    return copied


def empty_workspace() -> dict[str, Any]:
    return {
        "goals": {}, "documents": {}, "documentProfiles": {}, "playbooks": {}, "associations": {},
        "sessions": {}, "transcripts": {}, "recordings": {}, "files": {}, "voiceSample": None,
        "prefs": dict(DEFAULT_PREFS), "consents": dict(DEFAULT_CONSENTS), "preferences": {}, "lastUsed": None,
    }


class Workspace:
    """A loaded state plus a flag recording whether it must be saved."""

    def __init__(self, username: str, path: Path, state: dict[str, Any]) -> None:
        self.username = username
        self.path = path
        self.state = state
        self.dirty = False

    def changed(self) -> None:
        self.dirty = True

    @property
    def files(self) -> Path:
        return self.path / "files"

    def write_file(self, name: str, data: bytes) -> None:
        ensure_private_dir(self.files)
        atomic_write_bytes(self.files / name, data)


# Called once per account per process, under the lock, right after the first
# load. Returns callbacks to run once the state has been saved and unlocked.
FirstLoadHook = Callable[[Workspace], list[Callable[[], object]]]


class WorkspaceStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._locks: dict[str, asyncio.Lock] = {}
        self._loaded: set[str] = set()
        self._first_load_hooks: list[FirstLoadHook] = []

    def on_first_load(self, hook: FirstLoadHook) -> None:
        self._first_load_hooks.append(hook)

    def account_path(self, username: str | None) -> Path:
        if not username or not ACCOUNT_NAME.match(username):
            fail(401, "Sign in locally to continue.")
        return self.directory / username

    @asynccontextmanager
    async def open(self, username: str | None) -> AsyncIterator[Workspace]:
        """Lock, load and (if changed) save one account's workspace."""
        path = self.account_path(username)
        lock = self._locks.setdefault(username, asyncio.Lock())
        follow_ups: list[Callable[[], object]] = []
        async with lock:
            file = path / "workspace.json"
            try:
                state = {**empty_workspace(), **json.loads(file.read_text())}
            except FileNotFoundError:
                state = empty_workspace()
            workspace = Workspace(username, path, state)
            if username not in self._loaded:
                self._loaded.add(username)
                for hook in self._first_load_hooks:
                    follow_ups.extend(hook(workspace))
            yield workspace
            if workspace.dirty:
                ensure_private_dir(path)
                atomic_write_json(file, state)
        for start in follow_ups:
            start()
