"""Local accounts: administrator activation, member sign-up and sign-in.

Storage (unchanged from the JavaScript backend, so existing accounts work):

* one ``<username>.json`` per account, mode 0600, holding
  ``{"username", "role", "setupRequired", "credential": {"salt", "digest"}}``;
* the digest is scrypt(password, salt, N=2**17, r=8, p=1, 32 bytes), hex-encoded;
* ``admin-first-login.txt`` holds the one-time administrator setup code until
  the administrator chooses a password.

Sessions are kept in memory and keyed by *owner*, an opaque id the Electron
main process assigns to each window that signs in. Only one account can be
signed in at a time; the workspace and realtime engine act for that account.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from .fileio import atomic_write_json, create_exclusive_json, ensure_private_dir

USERNAME = re.compile(r"^[a-z][a-z0-9._-]{2,31}$")
FIRST_LOGIN_FILE = "admin-first-login.txt"
SETUP_CODE = re.compile(r"^[A-Za-z0-9_-]{32}$")
KDF = {"n": 2**17, "r": 8, "p": 1, "maxmem": 160 * 1024 * 1024, "dklen": 32}
MIN_NEW_PASSWORD_CHARS = 15
MAX_PASSWORD_BYTES = 256
FAILURE_COOLDOWN_S = 0.8


class AuthError(Exception):
    """A sign-in problem whose message is shown in the local account dialog."""


@dataclass(frozen=True)
class Account:
    """What the rest of the backend knows about a signed-in user."""

    username: str
    role: str  # "admin" or "member"

    def public(self) -> dict[str, str]:
        return {"username": self.username, "role": self.role}


@dataclass
class Session:
    account: Account
    # Bearer token the app presents when opening a realtime interview socket.
    token: str


def normalize_username(value: object) -> str:
    if not isinstance(value, str):
        raise AuthError("Enter a valid username.")
    normalized = value.strip().lower()
    if not USERNAME.match(normalized):
        raise AuthError("Use 3–32 letters, numbers, dots, dashes or underscores. Start with a letter.")
    return normalized


def check_password(value: object, *, choosing: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value.encode()) > MAX_PASSWORD_BYTES:
        raise AuthError("Enter a valid password.")
    if choosing and len(value) < MIN_NEW_PASSWORD_CHARS:
        raise AuthError(f"Use at least {MIN_NEW_PASSWORD_CHARS} characters for your password.")
    return value


def derive(secret: str, salt_hex: str | None = None) -> dict[str, str]:
    """Hash ``secret``; pass the stored salt to reproduce an existing digest."""
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.scrypt(secret.encode(), salt=salt, **KDF)
    return {"salt": salt.hex(), "digest": digest.hex()}


def verify(secret: str, credential: dict[str, str]) -> bool:
    expected = bytes.fromhex(credential["digest"])
    actual = bytes.fromhex(derive(secret, credential["salt"])["digest"])
    return hmac.compare_digest(expected, actual)


def read_account(directory: Path, name: str) -> dict | None:
    """Load and validate one account record; ``None`` if it does not exist."""
    try:
        value = json.loads((directory / f"{name}.json").read_text())
    except FileNotFoundError:
        return None
    credential = value.get("credential") or {}
    if (value.get("username") != name or value.get("role") not in ("admin", "member")
            or not re.fullmatch(r"[a-f0-9]{32}", str(credential.get("salt", "")))
            or not re.fullmatch(r"[a-f0-9]{64}", str(credential.get("digest", "")))):
        raise ValueError("Invalid local account record.")
    return value


def provision_admin(directory: Path) -> str | None:
    """Create the administrator with a one-time setup code (idempotent).

    Returns the setup code when one is pending, ``None`` once the administrator
    already exists and is active.
    """
    ensure_private_dir(directory)
    existing = read_account(directory, "admin")
    code_path = directory / FIRST_LOGIN_FILE
    if existing:
        return code_path.read_text().strip() if existing.get("setupRequired") and code_path.exists() else None
    code = secrets.token_urlsafe(24)
    try:
        with open(code_path, "x") as handle:
            handle.write(code + "\n")
        code_path.chmod(0o600)
    except FileExistsError:
        code = code_path.read_text().strip()
        if not SETUP_CODE.match(code):
            raise ValueError("Invalid existing admin setup code.") from None
    create_exclusive_json(directory / "admin.json", {
        "username": "admin", "role": "admin", "setupRequired": True, "credential": derive(code),
    })
    return code


class AccountService:
    """Sign-in state for the local accounts in one directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.sessions: dict[str, Session] = {}
        # Compared against when the username does not exist, so a missing
        # account costs the same time as a wrong password.
        self._dummy = {"salt": secrets.token_hex(16), "digest": "0" * 64}
        self._busy = False
        self._retry_at = 0.0

    # -- helpers -------------------------------------------------------------

    async def _exclusive(self, action):
        """Run one credential operation at a time, with a pause after failures."""
        if self._busy or time.monotonic() < self._retry_at:
            raise AuthError("Please wait a moment before trying again.")
        self._busy = True
        try:
            return await action()
        finally:
            self._busy = False

    def _failed(self, message: str) -> AuthError:
        self._retry_at = time.monotonic() + FAILURE_COOLDOWN_S
        return AuthError(message)

    def _start(self, owner: str, record: dict) -> Session:
        session = Session(Account(record["username"], record["role"]), secrets.token_urlsafe(32))
        self.sessions[owner] = session
        return session

    # -- queries -------------------------------------------------------------

    def current(self) -> Session | None:
        """The signed-in session, if any."""
        return next(iter(self.sessions.values()), None)

    def session(self, owner: str) -> Session | None:
        return self.sessions.get(owner)

    def status(self) -> dict[str, bool]:
        record = read_account(self.directory, "admin")
        return {"setupRequired": bool(record and record.get("setupRequired"))}

    def list_accounts(self, owner: str) -> list[dict[str, str]]:
        session = self.sessions.get(owner)
        if not session or session.account.role != "admin":
            raise AuthError("Administrator access is required.")
        names = sorted(p.stem for p in self.directory.glob("*.json") if USERNAME.match(p.stem))
        records = [read_account(self.directory, name) for name in names]
        return [{"username": r["username"], "role": r["role"]} for r in records if r]

    # -- commands ------------------------------------------------------------

    async def sign_in(self, owner: str, username: object, password: object) -> Session:
        async def action() -> Session:
            record = read_account(self.directory, normalize_username(username))
            valid = await asyncio.to_thread(verify, check_password(password), (record or {}).get("credential") or self._dummy)
            if not record or not valid:
                raise self._failed("The username or password is incorrect.")
            if record.get("setupRequired"):
                raise AuthError("Activate the administrator account before signing in.")
            return self._start(owner, record)
        return await self._exclusive(action)

    async def register(self, owner: str, username: object, password: object) -> Session:
        async def action() -> Session:
            name = normalize_username(username)
            if name == "admin" or read_account(self.directory, name):
                raise AuthError("This username is already in use.")
            credential = await asyncio.to_thread(derive, check_password(password, choosing=True))
            record = {"username": name, "role": "member", "setupRequired": False, "credential": credential}
            ensure_private_dir(self.directory)
            try:
                create_exclusive_json(self.directory / f"{name}.json", record)
            except FileExistsError:
                raise AuthError("This username is already in use.") from None
            return self._start(owner, record)
        return await self._exclusive(action)

    async def activate(self, owner: str, code: object, new_password: object) -> Session:
        async def action() -> Session:
            record = read_account(self.directory, "admin")
            if not record or not record.get("setupRequired"):
                raise AuthError("The administrator account is already active.")
            if not await asyncio.to_thread(verify, check_password(code), record["credential"]):
                raise self._failed("The setup code is incorrect.")
            credential = await asyncio.to_thread(derive, check_password(new_password, choosing=True))
            updated = {**record, "setupRequired": False, "credential": credential}
            atomic_write_json(self.directory / "admin.json", updated)
            # The code stops working as soon as the new password is saved.
            (self.directory / FIRST_LOGIN_FILE).unlink(missing_ok=True)
            return self._start(owner, updated)
        return await self._exclusive(action)

    def sign_out(self, owner: str | None = None) -> Account | None:
        """End one owner's session, or every session when ``owner`` is ``None``.

        Returns the account that was signed in before, so callers can release
        its live interviews.
        """
        previous = self.current()
        if owner is None:
            self.sessions.clear()
        else:
            self.sessions.pop(owner, None)
        return previous.account if previous else None
