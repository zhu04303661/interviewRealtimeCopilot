"""OpenAI relay for the desktop app: the app sends its device token, the server adds the OpenAI key and meters usage.

    /api/v1/openai/v1/models                     GET
    /api/v1/openai/v1/responses                  POST (JSON or server-sent events)
    /api/v1/openai/v1/audio/transcriptions       POST (multipart)
    /api/v1/openai/v1/realtime?…                 WebSocket (speech-to-speech and transcription)
    /api/v1/openai/v1/live/sessions              WebSocket

Every usage object OpenAI reports (response bodies, `response.completed` stream events,
Realtime `response.done` and transcription-completed events) is metered. A request is
refused with 402 when the account's balance is used up; an open WebSocket gets an
`error` event with code `quota_exceeded` and is closed.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from typing import Any

import aiohttp
from aiohttp import web

from .billing import Billing

HTTP_PATHS = {"v1/models", "v1/responses", "v1/audio/transcriptions"}
WS_PATHS = {"v1/realtime", "v1/live/sessions"}


def quota_body(origin: str) -> dict[str, Any]:
    return {"error": {"code": "quota_exceeded", "type": "insufficient_quota",
                      "message": f"Your monthly AI allowance is used up. Subscribe at {origin}/pricing.html to continue."}}


def usages(event: Any) -> list[tuple[str | None, dict[str, Any]]]:
    """(model, usage) pairs found in one OpenAI JSON payload or event."""
    if not isinstance(event, dict):
        return []
    found = []
    if isinstance(event.get("usage"), dict):
        found.append((event.get("model"), event["usage"]))
    response = event.get("response")
    if isinstance(response, dict) and isinstance(response.get("usage"), dict):
        found.append((response.get("model"), response["usage"]))
    return found


def setup(app: web.Application, billing: Billing, origin: str, upstream: str, current_user: Callable[[web.Request], Any]) -> None:
    upstream = upstream.rstrip("/")
    # Optional proxy for reaching OpenAI (development behind a proxy); aiohttp needs it passed to WebSockets explicitly.
    proxy = {"proxy": p} if (p := os.environ.get("IRC_OPENAI_PROXY")) else {}
    ws_upstream = "wss://" + upstream[8:] if upstream.startswith("https://") else "ws://" + upstream[7:]

    async def client(app_: web.Application):
        app_["openai_http"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=20))
        yield
        await app_["openai_http"].close()

    app.cleanup_ctx.append(client)

    def fail(status: int, message: str, code: str = "unauthorized") -> web.Response:
        return web.json_response({"error": {"code": code, "message": message}}, status=status)

    def meter(user, model_hint: str, endpoint: str, payload: Any) -> None:
        for model, usage in usages(payload):
            billing.record(user, model or model_hint, endpoint, usage)

    async def handle(request: web.Request) -> web.StreamResponse:
        user = current_user(request)
        if not user:
            return fail(401, "Sign in to the app to use AI features.")
        tail = request.match_info["tail"]
        key = billing.openai_key()
        if not key:
            return fail(503, "The AI service is not configured yet.", "not_configured")
        if billing.balance_micro(user) <= 0:
            return web.json_response(quota_body(origin), status=402)
        if tail in WS_PATHS:
            return await websocket(request, user, tail, key)
        if tail not in HTTP_PATHS:
            return fail(404, "Not available through the relay.", "not_found")
        headers = {"Authorization": f"Bearer {key}"}
        if request.content_type:
            headers["Content-Type"] = request.headers["Content-Type"]
        body = await request.read()
        model = "transcribe" if "transcriptions" in tail else ""
        if request.content_type == "application/json" and body:
            try:
                model = str(json.loads(body).get("model") or "")
            except ValueError:
                pass
        if "transcriptions" in tail:
            model = next((m for m in ("gpt-4o-mini-transcribe", "gpt-4o-transcribe") if m.encode() in body[:4096]), "gpt-4o-transcribe")
        async with request.app["openai_http"].request(request.method, f"{upstream}/{tail}", params=request.query, data=body or None,
                                                       headers=headers, **proxy) as up:
            if up.content_type == "text/event-stream":
                response = web.StreamResponse(status=up.status, headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
                await response.prepare(request)
                buffer = b""
                async for chunk in up.content.iter_any():
                    await response.write(chunk)
                    buffer += chunk
                    *lines, buffer = buffer.split(b"\n")
                    for line in lines:
                        if line.startswith(b"data:") and b'"usage"' in line:
                            try:
                                meter(user, model, tail, json.loads(line[5:]))
                            except ValueError:
                                pass
                await response.write_eof()
                return response
            data = await up.read()
            if up.status < 400 and up.content_type == "application/json":
                try:
                    meter(user, model, tail, json.loads(data))
                except ValueError:
                    pass
            return web.Response(status=up.status, body=data, content_type=up.content_type)

    async def websocket(request: web.Request, user, tail: str, key: str) -> web.StreamResponse:
        model = request.query.get("model") or ("gpt-4o-transcribe" if request.query.get("intent") == "transcription" else "gpt-live" if "live" in tail else "gpt-realtime")
        headers = {"Authorization": f"Bearer {key}"}
        if "OpenAI-Beta" in request.headers:
            headers["OpenAI-Beta"] = request.headers["OpenAI-Beta"]
        try:
            up = await request.app["openai_http"].ws_connect(f"{ws_upstream}/{tail}", params=request.query, headers=headers, heartbeat=30,
                                                          max_msg_size=0, **proxy)
        except aiohttp.WSServerHandshakeError as error:
            return fail(error.status or 502, "OpenAI refused the connection.", "upstream")
        down = web.WebSocketResponse(heartbeat=30, max_msg_size=0)
        await down.prepare(request)

        async def to_openai() -> None:
            async for msg in down:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await up.send_str(msg.data)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await up.send_bytes(msg.data)

        async def to_app() -> None:
            async for msg in up:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await down.send_str(msg.data)
                    if '"usage"' in msg.data:
                        try:
                            event = json.loads(msg.data)
                        except ValueError:
                            continue
                        meter(user, model, tail, event)
                        if billing.balance_micro(user) <= 0:
                            await down.send_str(json.dumps({"type": "error", **quota_body(origin)}))
                            return
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await down.send_bytes(msg.data)

        tasks = [asyncio.create_task(to_openai()), asyncio.create_task(to_app())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await up.close()
            await down.close()
        return down

    app.router.add_route("*", "/api/v1/openai/{tail:v1/.+}", handle)
