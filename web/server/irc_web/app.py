"""Interview Realtime Copilot website: pages, accounts and Stripe subscriptions.

Static pages are served from ../static. The API keeps accounts and
subscriptions in SQLite:

    POST /api/signup      {email, password}         create an account, sign in
    POST /api/login       {email, password}         sign in (HttpOnly session cookie)
    POST /api/logout
    GET  /api/me                                    account and subscription
    POST /api/checkout    {plan: "monthly"|"yearly"} Stripe Checkout URL
    POST /api/portal                                Stripe billing portal URL
    POST /api/waitlist    {email, topic}            notify-me sign-ups
    POST /api/stripe/webhook                        subscription updates from Stripe

Configuration (environment): IRC_WEB_DB, IRC_WEB_ORIGIN (public https origin),
STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET. Without Stripe keys, checkout
answers 503 and everything else works.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

STATIC = Path(__file__).resolve().parent.parent.parent / "static"
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
SESSION_DAYS = 30
PLANS = {  # amounts in cents
    "monthly": {"amount": 2900, "interval": "month", "name": "Interview Realtime Copilot Pro (monthly)"},
    "yearly": {"amount": 19900, "interval": "year", "name": "Interview Realtime Copilot Pro (yearly)"},
}
KDF = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
SCHEMA = """
create table if not exists users (id integer primary key, email text unique not null, password text not null,
  created_at integer not null, stripe_customer text, plan text, status text, current_period_end integer);
create table if not exists sessions (token text primary key, user_id integer not null, expires_at integer not null);
create table if not exists waitlist (email text not null, topic text not null, created_at integer not null, primary key (email, topic));
create table if not exists stripe_events (id text primary key, received_at integer not null);
"""


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    return salt.hex() + ":" + hashlib.scrypt(password.encode(), salt=salt, **KDF).hex()


def check_password(password: str, stored: str) -> bool:
    salt, _, digest = stored.partition(":")
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)).partition(":")[2], digest)


def verify_stripe_signature(payload: bytes, header: str, secret: str, tolerance: int = 300) -> bool:
    """Stripe-Signature: t=<timestamp>,v1=<hmac-sha256 of "t.payload">."""
    parts = dict(item.split("=", 1) for item in header.split(",") if "=" in item)
    try:
        timestamp = int(parts.get("t", ""))
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    signatures = [value for key, value in (item.split("=", 1) for item in header.split(",") if "=" in item) if key == "v1"]
    return abs(time.time() - timestamp) <= tolerance and any(hmac.compare_digest(expected, s) for s in signatures)


class Store:
    def __init__(self, path: str) -> None:
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def user_by_email(self, email: str) -> sqlite3.Row | None:
        return self.db.execute("select * from users where email = ?", (email,)).fetchone()

    def user_by_token(self, token: str) -> sqlite3.Row | None:
        return self.db.execute("select u.* from users u join sessions s on s.user_id = u.id where s.token = ? and s.expires_at > ?",
                               (token, int(time.time()))).fetchone()

    def start_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        self.db.execute("insert into sessions values (?, ?, ?)", (token, user_id, int(time.time()) + SESSION_DAYS * 86400))
        return token


def public_user(user: sqlite3.Row) -> dict[str, Any]:
    active = user["status"] in ("active", "trialing")
    return {"email": user["email"], "plan": user["plan"] if active else "free", "status": user["status"] or "none",
            "current_period_end": user["current_period_end"]}


def build_app(*, db_path: str | None = None, stripe_api: str = "https://api.stripe.com") -> web.Application:
    store = Store(db_path or os.environ.get("IRC_WEB_DB", "irc-web.sqlite3"))
    origin = os.environ.get("IRC_WEB_ORIGIN", "http://localhost:8090").rstrip("/")
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    attempts: dict[str, list[float]] = {}

    def fail(status: int, message: str) -> web.Response:
        return web.json_response({"error": message}, status=status)

    @web.middleware
    async def guard(request: web.Request, handler):
        # State-changing requests must come from our own pages (or be Stripe's signed webhook).
        if (request.method == "POST" and request.path != "/api/stripe/webhook"
                and request.headers.get("Origin", "").rstrip("/") != origin):
            return fail(403, "Cross-site request refused.")
        response = await handler(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    def limited(request: web.Request, key: str, limit: int = 10, window: int = 600) -> bool:
        now = time.monotonic()
        recent = [t for t in attempts.get(key, []) if now - t < window]
        attempts[key] = recent + [now]
        return len(recent) >= limit

    def current(request: web.Request) -> sqlite3.Row | None:
        token = request.cookies.get("irc_session", "")
        return store.user_by_token(token) if token else None

    def signed_in(user: sqlite3.Row, token: str) -> web.Response:
        response = web.json_response({"user": public_user(user)})
        response.set_cookie("irc_session", token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="Lax",
                            secure=origin.startswith("https://"), path="/")
        return response

    async def credentials(request: web.Request) -> tuple[str, str]:
        body = await request.json()
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        return email, password

    async def signup(request: web.Request) -> web.Response:
        if limited(request, f"signup:{request.remote}", 5):
            return fail(429, "Too many attempts. Try again later.")
        email, password = await credentials(request)
        if not EMAIL.match(email):
            return fail(422, "Enter a valid email address.")
        if not 10 <= len(password) <= 200:
            return fail(422, "Use a password of at least 10 characters.")
        try:
            cursor = store.db.execute("insert into users (email, password, created_at) values (?, ?, ?)",
                                      (email, hash_password(password), int(time.time())))
        except sqlite3.IntegrityError:
            return fail(409, "An account with this email already exists.")
        user = store.db.execute("select * from users where id = ?", (cursor.lastrowid,)).fetchone()
        return signed_in(user, store.start_session(user["id"]))

    async def login(request: web.Request) -> web.Response:
        email, password = await credentials(request)
        if limited(request, f"login:{email}") or limited(request, f"login-ip:{request.remote}", 30):
            return fail(429, "Too many attempts. Try again later.")
        user = store.user_by_email(email)
        if not user or not check_password(password, user["password"]):
            return fail(401, "The email or password is incorrect.")
        return signed_in(user, store.start_session(user["id"]))

    async def logout(request: web.Request) -> web.Response:
        store.db.execute("delete from sessions where token = ?", (request.cookies.get("irc_session", ""),))
        response = web.json_response({"ok": True})
        response.del_cookie("irc_session", path="/")
        return response

    async def me(request: web.Request) -> web.Response:
        user = current(request)
        return web.json_response({"user": public_user(user) if user else None, "payments": bool(stripe_key)})

    async def stripe(path: str, form: dict[str, str]) -> dict[str, Any]:
        async with aiohttp.ClientSession() as http, http.post(f"{stripe_api}{path}", data=form,
                                                              headers={"Authorization": f"Bearer {stripe_key}"}) as response:
            payload = await response.json()
            if response.status >= 400:
                raise web.HTTPBadGateway(text=json.dumps({"error": (payload.get("error") or {}).get("message", "Stripe error")}),
                                         content_type="application/json")
            return payload

    async def checkout(request: web.Request) -> web.Response:
        user = current(request)
        if not user:
            return fail(401, "Sign in to subscribe.")
        if not stripe_key:
            return fail(503, "Payments are not configured yet.")
        plan = PLANS.get(str((await request.json()).get("plan")))
        if not plan:
            return fail(422, "Choose a plan.")
        key = next(k for k, v in PLANS.items() if v is plan)
        form = {
            "mode": "subscription", "client_reference_id": str(user["id"]), "customer_email": user["email"],
            "success_url": f"{origin}/account.html?checkout=success", "cancel_url": f"{origin}/pricing.html?checkout=cancelled",
            "line_items[0][quantity]": "1", "line_items[0][price_data][currency]": "usd",
            "line_items[0][price_data][unit_amount]": str(plan["amount"]),
            "line_items[0][price_data][recurring][interval]": plan["interval"],
            "line_items[0][price_data][product_data][name]": plan["name"],
            "metadata[plan]": key, "subscription_data[metadata][plan]": key,
        }
        if user["stripe_customer"]:
            form.pop("customer_email")
            form["customer"] = user["stripe_customer"]
        session = await stripe("/v1/checkout/sessions", form)
        return web.json_response({"url": session["url"]})

    async def portal(request: web.Request) -> web.Response:
        user = current(request)
        if not user or not user["stripe_customer"]:
            return fail(404, "No subscription to manage.")
        if not stripe_key:
            return fail(503, "Payments are not configured yet.")
        session = await stripe("/v1/billing_portal/sessions", {"customer": user["stripe_customer"], "return_url": f"{origin}/account.html"})
        return web.json_response({"url": session["url"]})

    async def waitlist(request: web.Request) -> web.Response:
        if limited(request, f"waitlist:{request.remote}", 10):
            return fail(429, "Too many attempts. Try again later.")
        body = await request.json()
        email = str(body.get("email", "")).strip().lower()
        topic = str(body.get("topic", "download"))[:40]
        if not EMAIL.match(email):
            return fail(422, "Enter a valid email address.")
        store.db.execute("insert or ignore into waitlist values (?, ?, ?)", (email, topic, int(time.time())))
        return web.json_response({"ok": True})

    async def webhook(request: web.Request) -> web.Response:
        payload = await request.read()
        if not webhook_secret or not verify_stripe_signature(payload, request.headers.get("Stripe-Signature", ""), webhook_secret):
            return fail(400, "Invalid signature.")
        event = json.loads(payload)
        if store.db.execute("select 1 from stripe_events where id = ?", (event.get("id"),)).fetchone():
            return web.json_response({"ok": True})  # already handled
        store.db.execute("insert into stripe_events values (?, ?)", (event.get("id"), int(time.time())))
        kind, obj = event.get("type"), (event.get("data") or {}).get("object") or {}
        if kind == "checkout.session.completed" and obj.get("client_reference_id"):
            store.db.execute("update users set stripe_customer = ?, plan = ?, status = 'active' where id = ?",
                             (obj.get("customer"), (obj.get("metadata") or {}).get("plan"), int(obj["client_reference_id"])))
        elif kind in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
            status = "canceled" if kind.endswith("deleted") else obj.get("status")
            period_end = obj.get("current_period_end") or ((obj.get("items") or {}).get("data") or [{}])[0].get("current_period_end")
            store.db.execute("update users set status = ?, plan = coalesce(?, plan), current_period_end = ? where stripe_customer = ?",
                             (status, (obj.get("metadata") or {}).get("plan"), period_end, obj.get("customer")))
        return web.json_response({"ok": True})

    async def page(request: web.Request) -> web.StreamResponse:
        name = request.match_info.get("name") or "index.html"
        path = (STATIC / name).resolve()
        if STATIC not in path.parents or not path.is_file():
            path = STATIC / "404.html"
            return web.FileResponse(path, status=404)
        return web.FileResponse(path)

    app = web.Application(middlewares=[guard], client_max_size=256 * 1024)
    app.add_routes([
        web.post("/api/signup", signup), web.post("/api/login", login), web.post("/api/logout", logout),
        web.get("/api/me", me), web.post("/api/checkout", checkout), web.post("/api/portal", portal),
        web.post("/api/waitlist", waitlist), web.post("/api/stripe/webhook", webhook),
        web.get("/", page), web.get("/{name:.+}", page),
    ])
    return app


def main() -> None:
    web.run_app(build_app(), host=os.environ.get("IRC_WEB_HOST", "127.0.0.1"), port=int(os.environ.get("IRC_WEB_PORT", "8090")))


if __name__ == "__main__":
    main()
