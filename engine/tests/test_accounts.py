"""Local accounts: activation, sign-in, members, sessions and compatibility with existing records."""

from __future__ import annotations

import asyncio
import json

import pytest

from frlocal.accounts import FIRST_LOGIN_FILE, AccountService, AuthError, provision_admin, verify

from .conftest import ADMIN_PASSWORD

# Produced by the earlier JavaScript backend (Node's crypto.scryptSync, same parameters).
NODE_CREDENTIAL = {"salt": "00112233445566778899aabbccddeeff",
                   "digest": "383c0968df8f334694cccb4bbe115d0f1d4df21157c63ab9d7a040ffcaaab7c6"}


def test_digest_matches_records_written_by_the_javascript_backend():
    assert verify("correct horse battery staple", NODE_CREDENTIAL)
    assert not verify("wrong password", NODE_CREDENTIAL)


def test_provisioning_is_idempotent_and_private(tmp_path):
    code = provision_admin(tmp_path)
    assert code and len(code) == 32
    assert provision_admin(tmp_path) == code
    assert (tmp_path / "admin.json").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / FIRST_LOGIN_FILE).stat().st_mode & 0o777 == 0o600
    record = json.loads((tmp_path / "admin.json").read_text())
    assert record["setupRequired"] is True and record["role"] == "admin"


async def test_activation_sign_in_and_members(tmp_path):
    code = provision_admin(tmp_path)
    service = AccountService(tmp_path)
    assert service.status() == {"setupRequired": True}
    with pytest.raises(AuthError, match="Activate the administrator"):
        await service.sign_in("w1", "admin", code)
    await asyncio.sleep(0.9)
    with pytest.raises(AuthError, match="setup code is incorrect"):
        await service.activate("w1", "x" * 32, ADMIN_PASSWORD)
    with pytest.raises(AuthError, match="wait a moment"):
        await service.activate("w1", code, ADMIN_PASSWORD)  # cool-down after a failure
    await asyncio.sleep(0.9)
    with pytest.raises(AuthError, match="at least 15 characters"):
        await service.activate("w1", code, "short")
    session = await service.activate("w1", code, ADMIN_PASSWORD)
    assert session.account.public() == {"username": "admin", "role": "admin"}
    assert len(session.token) >= 32
    assert not (tmp_path / FIRST_LOGIN_FILE).exists()
    assert service.status() == {"setupRequired": False}

    assert service.sign_out().username == "admin"
    member = await service.register("w2", "Test.Member", "member-password-long")
    assert member.account.public() == {"username": "test.member", "role": "member"}
    with pytest.raises(AuthError, match="Administrator access"):
        service.list_accounts("w2")
    with pytest.raises(AuthError, match="already in use"):
        await service.register("w3", "admin", "another-long-password")
    service.sign_out()
    await service.sign_in("w1", "ADMIN", ADMIN_PASSWORD)
    assert service.list_accounts("w1") == [{"username": "admin", "role": "admin"}, {"username": "test.member", "role": "member"}]


async def test_wrong_password_and_unknown_user_fail_the_same_way(tmp_path):
    code = provision_admin(tmp_path)
    service = AccountService(tmp_path)
    await service.activate("w", code, ADMIN_PASSWORD)
    service.sign_out()
    with pytest.raises(AuthError, match="username or password is incorrect"):
        await service.sign_in("w", "admin", "not-the-password")
    await asyncio.sleep(0.9)
    with pytest.raises(AuthError, match="username or password is incorrect"):
        await service.sign_in("w", "nobody", "not-the-password")
    await asyncio.sleep(0.9)
    with pytest.raises(AuthError, match="Start with a letter"):
        await service.sign_in("w", "1bad", "x")


async def test_bridge_endpoints_report_errors_as_messages(backend):
    status = await backend.call("GET", "/local/auth/status")
    assert status == {"ok": True, "value": {"setupRequired": True}}
    failed = await backend.call("POST", "/local/auth/sign-in", json={"owner": "1", "username": "admin", "password": "x"})
    assert failed["ok"] is False and "incorrect" in failed["error"]
    assert (await backend.call("GET", "/local/auth/session", params={"owner": "1"}))["value"] is None
    await asyncio.sleep(0.9)  # failed attempts start a short cool-down
    await backend.sign_in_admin()
    current = await backend.call("GET", "/local/auth/session", params={"owner": "1"})
    assert current["value"]["account"] == {"username": "admin", "role": "admin"}
    assert current["value"]["token"] == backend.session_token


async def test_every_request_needs_the_bridge_token(backend):
    async with backend.session.get(backend.url("/local/health"), headers={"Authorization": "Bearer wrong"}) as response:
        assert response.status == 403
    assert (await backend.call("GET", "/local/health")) == {"ok": True}
