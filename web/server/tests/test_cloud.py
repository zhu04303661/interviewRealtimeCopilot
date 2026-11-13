import json

import aiohttp
import pytest
from aiohttp import web

from irc_web.app import Store, build_app
from irc_web.billing import Allowances, Billing

ORIGIN = "http://localhost:8090"
USAGE = {"input_tokens": 1000, "output_tokens": 200, "input_tokens_details": {"cached_tokens": 0}}


@pytest.fixture
async def cloud(aiohttp_client, tmp_path, monkeypatch):
    seen = []

    async def responses(request):
        body = await request.json()
        seen.append(("responses", request.headers.get("Authorization"), body))
        if body.get("stream"):
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            await response.write(b'data: {"type":"response.output_text.delta","delta":"Hi"}\n\n')
            await response.write(b'data: {"type":"response.completed","response":{"model":"gpt-5","usage":' + json.dumps(USAGE).encode() + b"}}\n\n")
            await response.write_eof()
            return response
        return web.json_response({"model": "gpt-5", "output_text": "ok", "usage": USAGE})

    async def realtime(request):
        seen.append(("realtime", request.headers.get("Authorization"), dict(request.query)))
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT and json.loads(msg.data).get("type") == "response.create":
                await ws.send_str(json.dumps({"type": "response.done", "response": {"usage": {
                    "input_tokens": 600, "output_tokens": 300, "input_token_details": {"audio_tokens": 500, "cached_tokens": 0},
                    "output_token_details": {"audio_tokens": 250}}}}))
            elif msg.type == aiohttp.WSMsgType.BINARY:
                await ws.send_bytes(msg.data)
        return ws

    openai = web.Application()
    openai.router.add_post("/v1/responses", responses)
    openai.router.add_get("/v1/realtime", realtime)
    upstream = await aiohttp_client(openai)
    monkeypatch.setenv("IRC_WEB_ORIGIN", ORIGIN)
    store_path = str(tmp_path / "db.sqlite3")
    store = Store(store_path)
    billing = Billing(store.db, Allowances(free_micro=50_000, pro_micro=1_000_000), secret="test-secret")
    billing.set_openai_key("sk-server-key")
    client = await aiohttp_client(build_app(db_path=store_path, openai_upstream=str(upstream.make_url("")).rstrip("/"), billing=billing))
    client.seen, client.billing = seen, billing
    return client


async def device(client, email="app@example.com"):
    response = await client.post("/api/v1/auth/register", json={"email": email, "password": "long-enough-1", "device": "MacBook"})
    assert response.status == 200
    data = await response.json()
    assert data["token"].startswith("irc_") and data["user"]["usage"]["allowance_usd"] == 0.05
    return {"Authorization": f"Bearer {data['token']}"}


async def test_device_login_and_me(cloud):
    auth = await device(cloud)
    me = await (await cloud.get("/api/v1/me", headers=auth)).json()
    assert me["user"]["email"] == "app@example.com" and me["user"]["plan"] == "free"
    assert (await cloud.post("/api/v1/auth/login", json={"email": "app@example.com", "password": "wrong-password"})).status == 401
    login = await cloud.post("/api/v1/auth/login", json={"email": "app@example.com", "password": "long-enough-1"})
    assert (await login.json())["token"] != auth["Authorization"][7:]
    await cloud.post("/api/v1/auth/logout", headers=auth)
    assert (await cloud.get("/api/v1/me", headers=auth)).status == 401
    assert (await cloud.post("/api/v1/openai/v1/responses", json={}, headers=auth)).status == 401


async def test_relay_uses_server_key_and_meters_json_and_stream(cloud):
    auth = await device(cloud)
    response = await cloud.post("/api/v1/openai/v1/responses", json={"model": "gpt-5", "input": "hi"}, headers=auth)
    assert (await response.json())["output_text"] == "ok"
    assert cloud.seen[-1][1] == "Bearer sk-server-key"  # the device token never reaches OpenAI
    stream = await cloud.post("/api/v1/openai/v1/responses", json={"model": "gpt-5", "input": "hi", "stream": True}, headers=auth)
    assert b"response.completed" in await stream.read()
    usage = (await (await cloud.get("/api/v1/me", headers=auth)).json())["user"]["usage"]
    # default price: 1000 input x $1.25/1M + 200 output x $10/1M = $0.00325 per request
    assert usage["used_usd"] == pytest.approx(0.0065)


async def test_quota_exhaustion_blocks_and_credit_restores(cloud):
    auth = await device(cloud)
    for _ in range(16):  # $0.00325 each against a $0.05 allowance
        await cloud.post("/api/v1/openai/v1/responses", json={"model": "gpt-5", "input": "hi"}, headers=auth)
    blocked = await cloud.post("/api/v1/openai/v1/responses", json={"model": "gpt-5", "input": "hi"}, headers=auth)
    assert blocked.status == 402 and (await blocked.json())["error"]["code"] == "quota_exceeded"
    me = (await (await cloud.get("/api/v1/me", headers=auth)).json())["user"]
    assert me["usage"]["balance_usd"] == 0 and me["usage"]["used_percent"] == 100
    user = cloud.billing.user_for_token(auth["Authorization"][7:])
    cloud.billing.grant(user["id"], 1.0, "test")
    assert (await cloud.post("/api/v1/openai/v1/responses", json={"model": "gpt-5", "input": "hi"}, headers=auth)).status == 200


async def test_pro_plan_gets_the_larger_allowance(cloud):
    auth = await device(cloud)
    user = cloud.billing.user_for_token(auth["Authorization"][7:])
    cloud.billing.db.execute("update users set plan = 'monthly', status = 'active' where id = ?", (user["id"],))
    assert (await (await cloud.get("/api/v1/me", headers=auth)).json())["user"]["usage"]["allowance_usd"] == 1.0


async def test_realtime_websocket_relay_meters_audio(cloud):
    auth = await device(cloud)
    async with cloud.ws_connect("/api/v1/openai/v1/realtime?model=gpt-realtime-2.1", headers=auth) as ws:
        await ws.send_bytes(b"\x00\x01")
        assert (await ws.receive()).data == b"\x00\x01"
        await ws.send_str(json.dumps({"type": "response.create"}))
        event = json.loads((await ws.receive()).data)
        assert event["type"] == "response.done"
    assert cloud.seen[-1][1] == "Bearer sk-server-key" and cloud.seen[-1][2]["model"] == "gpt-realtime-2.1"
    usage = (await (await cloud.get("/api/v1/me", headers=auth)).json())["user"]["usage"]
    # gpt-realtime: 100 text in x $4 + 500 audio in x $32 + 50 text out x $16 + 250 audio out x $64 (per 1M)
    assert usage["used_usd"] == pytest.approx((100 * 4 + 500 * 32 + 50 * 16 + 250 * 64) / 1e6)


async def test_web_link_signs_the_browser_in_once(cloud):
    auth = await device(cloud)
    url = (await (await cloud.post("/api/v1/auth/web-link", json={"next": "/pricing.html"}, headers=auth)).json())["url"]
    path = url[len(ORIGIN):]
    first = await cloud.get(path, allow_redirects=False)
    assert first.status == 302 and first.headers["Location"] == "/pricing.html" and "irc_session" in first.cookies
    assert (await (await cloud.get("/api/me")).json())["user"]["email"] == "app@example.com"
    again = await cloud.get(path, allow_redirects=False)
    assert again.headers["Location"].startswith("/login.html")


async def test_openai_key_is_stored_encrypted(cloud):
    row = cloud.billing.db.execute("select ciphertext from provider_keys where active = 1").fetchone()
    assert b"sk-server-key" not in bytes(row[0]) and cloud.billing.openai_key() == "sk-server-key"
