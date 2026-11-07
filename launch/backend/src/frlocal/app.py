"""The aiohttp application: wiring, authentication and the bridge endpoints.

Every request must carry ``Authorization: Bearer <FRLOCAL_TOKEN>``; the
Electron main process generates the token when it starts this process, so no
other local program can use the backend even though it listens on loopback.

Bridge endpoints (used by the Electron main process, not by the app pages):

====================================  ============================================
``GET  /local/health``                readiness probe
``GET  /local/auth/status``           whether the administrator still needs activation
``GET  /local/auth/session``          the account signed in by ``owner``
``POST /local/auth/sign-in``          ``{owner, username, password}``
``POST /local/auth/register``         ``{owner, username, password}``
``POST /local/auth/activate``         ``{owner, code, newPassword}``
``GET  /local/auth/accounts``         administrator only
``POST /local/auth/sign-out``         ``{owner?}``; ends sessions and live interviews
``POST /local/documents/import``      ``{kind, filePath, filename, contentType}``
``POST /local/network``               ``{proxy}`` current system proxy for OpenAI
``GET  /realtime/{session_id}``       live interview WebSocket
``*    anything else``              the workspace API (see ``workspace.api``),
                                      with or without the ``/api`` prefix
====================================  ============================================

Auth endpoints answer ``{"ok": true, "value": …}`` or ``{"ok": false, "error": "…"}``
so the account dialog can show the message as is.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from aiohttp import web

from .accounts import AccountService, AuthError
from .config import Settings
from .errors import ApiError
from .openai import OpenAI
from .realtime.engine import RealtimeEngine
from .workspace.api import WorkspaceApi, json_fields
from .workspace.documents import DocumentService
from .workspace.store import WorkspaceStore

log = logging.getLogger(__name__)

SETTINGS_KEY = web.AppKey("settings", Settings)
API_KEY = web.AppKey("workspace_api", WorkspaceApi)
DOCUMENTS_KEY = web.AppKey("documents", DocumentService)
ENGINE_KEY = web.AppKey("engine", RealtimeEngine)
ACCOUNTS_KEY = web.AppKey("accounts", AccountService)
OPENAI_KEY = web.AppKey("openai", OpenAI)


def build_app(settings: Settings, *, openai: OpenAI | None = None) -> web.Application:
    openai = openai or OpenAI(settings.openai_base, settings.openai_ws_base, settings.env_file, settings.openai_proxy)
    accounts = AccountService(settings.accounts_dir)
    store = WorkspaceStore(settings.workspace_dir)
    documents = DocumentService(store, settings.limits)

    def current() -> tuple[str, str] | None:
        session = accounts.current()
        return (session.account.username, session.token) if session else None

    engine = RealtimeEngine(settings, openai, documents.read_text, current)
    api = WorkspaceApi(settings, store, documents, accounts, engine, openai)

    @web.middleware
    async def require_token(request: web.Request, handler):
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode(), f"Bearer {settings.token}".encode()):
            return web.json_response({"detail": "The local backend only accepts requests from the app."}, status=403)
        return await handler(request)

    def ok(value: Any = None) -> web.Response:
        return web.json_response({"ok": True, "value": value})

    def owner_of(body: dict[str, Any]) -> str:
        owner = body.get("owner")
        if not isinstance(owner, (str, int)):
            raise AuthError("Local accounts are only available in the main window.")
        return str(owner)

    async def auth_call(request: web.Request, action) -> web.Response:
        try:
            return ok(await action(await json_fields(request) if request.method == "POST" else dict(request.query)))
        except (AuthError, ApiError) as error:
            return web.json_response({"ok": False, "error": str(error)})
        except ValueError as error:
            log.warning("Account operation failed: %s", error)
            return web.json_response({"ok": False, "error": "Local authentication failed."})

    def signed_in(session) -> dict[str, Any]:
        return {"account": session.account.public(), "token": session.token}

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def status(request):
        return await auth_call(request, lambda _: _value(accounts.status()))

    async def session(request):
        async def action(query):
            found = accounts.session(owner_of(query))
            return signed_in(found) if found else None
        return await auth_call(request, action)

    async def sign_in(request):
        async def action(body):
            return signed_in(await accounts.sign_in(owner_of(body), body.get("username"), body.get("password")))
        return await auth_call(request, action)

    async def register(request):
        async def action(body):
            return signed_in(await accounts.register(owner_of(body), body.get("username"), body.get("password")))
        return await auth_call(request, action)

    async def activate(request):
        async def action(body):
            return signed_in(await accounts.activate(owner_of(body), body.get("code"), body.get("newPassword")))
        return await auth_call(request, action)

    async def list_accounts(request):
        return await auth_call(request, lambda query: _value(accounts.list_accounts(owner_of(query))))

    async def sign_out(request):
        async def action(body):
            owner = body.get("owner")
            previous = accounts.sign_out(str(owner) if owner is not None else None)
            if previous and (accounts.current() is None or accounts.current().account.username != previous.username):
                engine.clear_account(previous.username)
            return None
        return await auth_call(request, action)

    async def import_document(request: web.Request) -> web.Response:
        try:
            body = await json_fields(request)
            doc = await documents.import_file(api.username(), body.get("kind"), str(body.get("filePath") or ""),
                                              str(body.get("filename") or ""), body.get("contentType"))
            return web.json_response(doc)
        except ApiError as error:
            return web.json_response({"detail": error.detail}, status=error.status)

    async def network(request: web.Request) -> web.Response:
        proxy = (await json_fields(request)).get("proxy")
        await openai.set_proxy(proxy if isinstance(proxy, str) and proxy else None)
        return web.json_response({"ok": True})

    async def cleanup(_: web.Application) -> None:
        await engine.close()
        await openai.close()

    app = web.Application(middlewares=[require_token], client_max_size=64 * 1024 * 1024)
    app[SETTINGS_KEY] = settings
    app[API_KEY] = api
    app.router.add_get("/local/health", health)
    app.router.add_get("/local/auth/status", status)
    app.router.add_get("/local/auth/session", session)
    app.router.add_post("/local/auth/sign-in", sign_in)
    app.router.add_post("/local/auth/register", register)
    app.router.add_post("/local/auth/activate", activate)
    app.router.add_get("/local/auth/accounts", list_accounts)
    app.router.add_post("/local/auth/sign-out", sign_out)
    app.router.add_post("/local/documents/import", import_document)
    app.router.add_post("/local/network", network)
    app.router.add_get("/realtime/{session_id}", engine.handle_socket)
    # Everything else is the workspace API; the app calls it with and without the /api prefix.
    app.router.add_route("*", "/{tail:.*}", api.handle)
    app.on_cleanup.append(cleanup)
    app[DOCUMENTS_KEY] = documents
    app[ENGINE_KEY] = engine
    app[ACCOUNTS_KEY] = accounts
    app[OPENAI_KEY] = openai
    return app


async def _value(value: Any) -> Any:
    return value
