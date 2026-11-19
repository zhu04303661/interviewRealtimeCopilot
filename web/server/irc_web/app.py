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
    POST /api/track       {kind, page, source, lang}  anonymous visit counters (no cookies, no IP stored)
    POST /api/wish        {text, email?}            feature wishlist (stored; read in the admin dashboard)
    POST /api/interviews  {company, role, round, lang, text, outcome?, email?}   interview-experience posts (面经)
    GET  /api/interviews                            public board: approved posts, newest first
    GET  /interviews/{id} and /zh/interviews/{id}   public post pages (indexable)
    POST /api/admin/interview {id, approved|remove} moderate the board
    POST /api/stripe/webhook                        subscription updates from Stripe
    GET  /api/admin/overview|users|messages|usage   admin dashboard data (signed-in admin accounts only)

Desktop app (Authorization: Bearer <device token>; see billing.py and relay.py):

    POST /api/v1/auth/register|login {email, password, device}  -> {token, user}
    POST /api/v1/auth/logout                        revoke this device token
    GET  /api/v1/me                                 account, plan and this month's usage/balance
    POST /api/v1/auth/web-link {next}               one-time link that signs the browser in
    *    /api/v1/openai/v1/...                      metered OpenAI relay

Configuration (environment): IRC_WEB_DB, IRC_WEB_ORIGIN (public https origin), IRC_WEB_MIRRORS (comma-separated
origins of mirror sites that serve the pages themselves and proxy /api here, e.g. the China entry),
STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, IRC_WEB_SECRET (encrypts the stored OpenAI key),
IRC_OPENAI_UPSTREAM, IRC_FREE_ALLOWANCE_USD, IRC_PRO_ALLOWANCE_USD. Without Stripe keys, checkout
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

from . import relay
from .billing import Billing
from .billing import month_key as billing_month

STATIC = Path(__file__).resolve().parent.parent.parent / "static"
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
SESSION_DAYS = 30
CURRENCY = "gbp"
PLANS = {  # amounts in pence, before tax (Stripe adds the buyer's local tax at checkout)
    "monthly": {"amount": 2500, "interval": "month", "name": "Interview Realtime Copilot Pro (monthly)"},
    "yearly": {"amount": 16900, "interval": "year", "name": "Interview Realtime Copilot Pro (yearly)"},
}
KDF = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
SCHEMA = """
create table if not exists users (id integer primary key, email text unique not null, password text not null,
  created_at integer not null, stripe_customer text, plan text, status text, current_period_end integer);
create table if not exists sessions (token text primary key, user_id integer not null, expires_at integer not null);
create table if not exists waitlist (email text not null, topic text not null, created_at integer not null, primary key (email, topic));
create table if not exists wishes (id integer primary key, email text, text text not null, page text, created_at integer not null);
create table if not exists interview_posts (id integer primary key, company text not null, role text not null,
  round text not null, lang text not null, outcome text, text text not null, email text,
  approved integer not null default 0, created_at integer not null,
  user_id integer, questions text, audio integer not null default 0, rewarded integer not null default 0);
create table if not exists events (ts integer not null, kind text not null, page text not null, source text not null, lang text not null);
create index if not exists events_ts on events (ts);
create table if not exists stripe_events (id text primary key, received_at integer not null);
create table if not exists blog_posts (id integer primary key, slug text unique not null,
  title_en text not null, title_zh text, body_en text not null, body_zh text,
  published integer not null default 0, created_at integer not null, updated_at integer not null);
create table if not exists comments (id integer primary key, post_type text not null, post_id text not null,
  name text, body text not null, email text, approved integer not null default 0, created_at integer not null);
create index if not exists comments_post on comments (post_type, post_id, approved);
"""

BLOG_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")


def esc_text(s: object) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def plain_text(markdown: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[#*`>\[\]()!]", " ", markdown or "")).strip()


def render_markdown(text: str) -> str:
    """A deliberately small, safe markdown subset for admin-written posts: ## and ### headings, **bold**,
    `code`, [links](https://…), - bullet lists and blank-line paragraphs. Input is HTML-escaped first,
    so no raw markup can ever reach the page."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def inline(s: str) -> str:
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        return re.sub(r"\[([^\]]+)\]\((https?://[^)\s\"']+)\)", r'<a class="mail" href="\2" rel="noopener">\1</a>', s)

    out: list[str] = []
    buf: list[str] = []
    in_list = False

    def flush() -> None:
        nonlocal in_list
        if buf:
            out.append("<p>" + "<br>".join(buf) + "</p>")
            buf.clear()
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in escaped.split("\n"):
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("### "):
            flush()
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("## "):
            flush()
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("- "):
            if buf:
                out.append("<p>" + "<br>".join(buf) + "</p>")
                buf.clear()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            buf.append(inline(line))
    flush()
    return "".join(out)


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
        if "is_admin" not in {row[1] for row in self.db.execute("pragma table_info(users)")}:
            self.db.execute("alter table users add column is_admin integer not null default 0")
        posts_columns = {row[1] for row in self.db.execute("pragma table_info(interview_posts)")}
        for column in ("user_id integer", "questions text", "audio integer not null default 0", "rewarded integer not null default 0"):
            if column.split()[0] not in posts_columns:
                self.db.execute(f"alter table interview_posts add column {column}")

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
            "current_period_end": user["current_period_end"], **({"admin": True} if user["is_admin"] else {})}


def build_app(*, db_path: str | None = None, stripe_api: str = "https://api.stripe.com", openai_upstream: str | None = None,
              billing: Billing | None = None) -> web.Application:
    store = Store(db_path or os.environ.get("IRC_WEB_DB", "irc-web.sqlite3"))
    billing = billing or Billing(store.db)
    origin = os.environ.get("IRC_WEB_ORIGIN", "http://localhost:8090").rstrip("/")
    origins = {origin, *(o.strip().rstrip("/") for o in os.environ.get("IRC_WEB_MIRRORS", "").split(",") if o.strip())}

    def site(request: web.Request) -> str:
        """The site the visitor is on (ours or a mirror), for links that bring them back after Stripe."""
        seen = request.headers.get("Origin", "").rstrip("/")
        return seen if seen in origins else origin

    def client(request: web.Request) -> str:
        """The visitor's address for rate limits. Behind our own proxy (loopback peer) it is the first X-Forwarded-For
        entry, which the proxy sets itself (and extends only for trusted mirror proxies)."""
        forwarded = request.headers.get("X-Forwarded-For", "")
        return forwarded.split(",")[0].strip() if forwarded and request.remote in ("127.0.0.1", "::1") else str(request.remote)
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    attempts: dict[str, list[float]] = {}

    def fail(status: int, message: str) -> web.Response:
        return web.json_response({"error": message}, status=status)

    @web.middleware
    async def guard(request: web.Request, handler):
        # State-changing requests must come from our own pages (or be Stripe's signed webhook).
        # (The app's /api/v1 calls carry a Bearer token and no cookies, so they are not subject to this check.)
        if (request.method == "POST" and request.path != "/api/stripe/webhook" and not request.path.startswith("/api/v1/")
                and request.headers.get("Origin", "").rstrip("/") not in origins):
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
        if limited(request, f"signup:{client(request)}", 5):
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
        if limited(request, f"login:{email}") or limited(request, f"login-ip:{client(request)}", 30):
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

    def account(user: sqlite3.Row) -> dict[str, Any]:
        return {**public_user(user), "usage": billing.summary(user)}

    async def me(request: web.Request) -> web.Response:
        user = current(request)
        return web.json_response({"user": account(user) if user else None, "payments": bool(stripe_key)})

    def device_user(request: web.Request) -> sqlite3.Row | None:
        auth = request.headers.get("Authorization", "")
        return billing.user_for_token(auth[7:].strip()) if auth.startswith("Bearer ") else None

    async def device_auth(request: web.Request) -> web.Response:
        body = await request.json()
        name = str(body.get("device") or "desktop")
        if request.match_info["action"] == "register":
            response = await signup(request)
        else:
            response = await login(request)
        if response.status != 200:
            return response
        user = store.user_by_email(str(body.get("email", "")).strip().lower())
        return web.json_response({"token": billing.issue_token(user["id"], name), "user": account(user)})

    async def device_logout(request: web.Request) -> web.Response:
        billing.revoke_token(request.headers.get("Authorization", "")[7:].strip())
        return web.json_response({"ok": True})

    async def device_me(request: web.Request) -> web.Response:
        user = device_user(request)
        return web.json_response({"user": account(user)}) if user else fail(401, "Sign in again.")

    async def web_link(request: web.Request) -> web.Response:
        user = device_user(request)
        if not user:
            return fail(401, "Sign in again.")
        target = str((await request.json()).get("next") or "/account.html")
        target = target if target.startswith("/") and not target.startswith("//") else "/account.html"
        return web.json_response({"url": f"{origin}/auth/link?code={billing.issue_web_link(user['id'])}&next={target}"})

    async def redeem_link(request: web.Request) -> web.Response:
        user_id = billing.redeem_web_link(request.query.get("code", ""))
        target = request.query.get("next", "/account.html")
        target = target if target.startswith("/") and not target.startswith("//") else "/account.html"
        if not user_id:
            raise web.HTTPFound("/login.html?next=" + target)
        response = web.HTTPFound(target)
        response.set_cookie("irc_session", store.start_session(user_id), max_age=SESSION_DAYS * 86400, httponly=True, samesite="Lax",
                            secure=origin.startswith("https://"), path="/")
        raise response

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
            "success_url": f"{site(request)}/account.html?checkout=success", "cancel_url": f"{site(request)}/pricing.html?checkout=cancelled",
            "line_items[0][quantity]": "1", "line_items[0][price_data][currency]": CURRENCY,
            "line_items[0][price_data][unit_amount]": str(plan["amount"]),
            "line_items[0][price_data][recurring][interval]": plan["interval"],
            "line_items[0][price_data][product_data][name]": plan["name"],
            # Stripe Tax / Managed Payments need the product's tax category: software as a service, personal use.
            "line_items[0][price_data][product_data][tax_code]": os.environ.get("STRIPE_TAX_CODE", "txcd_10103000"),
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
        session = await stripe("/v1/billing_portal/sessions", {"customer": user["stripe_customer"], "return_url": f"{site(request)}/account.html"})
        return web.json_response({"url": session["url"]})

    async def waitlist(request: web.Request) -> web.Response:
        if limited(request, f"waitlist:{client(request)}", 10):
            return fail(429, "Too many attempts. Try again later.")
        body = await request.json()
        email = str(body.get("email", "")).strip().lower()
        topic = str(body.get("topic", "download"))[:40]
        if not EMAIL.match(email):
            return fail(422, "Enter a valid email address.")
        store.db.execute("insert or ignore into waitlist values (?, ?, ?)", (email, topic, int(time.time())))
        return web.json_response({"ok": True})

    async def track(request: web.Request) -> web.Response:
        """Counts a page view, a download click or a sign-up with its source (utm_source or referring site)."""
        agent = request.headers.get("User-Agent", "").lower()
        if any(word in agent for word in ("bot", "spider", "crawl", "headless", "curl", "python")) or limited(request, f"track:{client(request)}", 200):
            return web.json_response({"ok": True})
        body = await request.json()
        kind = str(body.get("kind", ""))
        if kind in ("view", "download", "signup"):
            store.db.execute("insert into events values (?, ?, ?, ?, ?)", (int(time.time()), kind, str(body.get("page", ""))[:120],
                             (str(body.get("source", "")).strip().lower() or "direct")[:60], str(body.get("lang", ""))[:5]))
        return web.json_response({"ok": True})

    async def wish(request: web.Request) -> web.Response:
        if limited(request, f"wish:{client(request)}", 10, 3600):
            return fail(429, "Too many attempts. Try again later.")
        body = await request.json()
        text = str(body.get("text", "")).strip()
        email = str(body.get("email", "")).strip().lower()
        if not 5 <= len(text) <= 3000:
            return fail(422, "Describe your idea in 5 to 3000 characters.")
        if email and not EMAIL.match(email):
            return fail(422, "Enter a valid email address, or leave it empty.")
        user = current(request)
        email = email or (user["email"] if user else "")
        store.db.execute("insert into wishes (email, text, page, created_at) values (?, ?, ?, ?)",
                         (email or None, text, str(body.get("page", ""))[:200], int(time.time())))
        return web.json_response({"ok": True})

    ROUNDS = {"hr", "oa", "technical", "system-design", "behavioral", "manager", "onsite", "other"}
    OUTCOMES = {"offer", "rejected", "waiting", "declined", ""}

    def story_fields(body: dict) -> dict | str:
        """Normalize and validate a story submission; the fields dict or an error message."""
        fields = {"company": str(body.get("company", "")).strip()[:100], "role": str(body.get("role", "")).strip()[:100],
                  "round": str(body.get("round", "")), "lang": str(body.get("lang", "")), "outcome": str(body.get("outcome", "")),
                  "email": str(body.get("email", "")).strip().lower()[:200], "text": str(body.get("text", "")).strip()}
        questions = body.get("questions")
        fields["questions"] = [str(q).strip()[:300] for q in questions if str(q).strip()][:20] if isinstance(questions, list) else []
        if not fields["company"] or not fields["role"]:
            return "Company and role are required."
        if fields["round"] not in ROUNDS or fields["lang"] not in ("en", "zh", "other"):
            return "Pick the interview stage and language."
        if fields["outcome"] not in OUTCOMES:
            return "Pick a valid outcome."
        if not 30 <= len(fields["text"]) <= 5000:
            return "Describe the interview in 30 to 5000 characters."
        if fields["email"] and not EMAIL.match(fields["email"]):
            return "Enter a valid email address, or leave it empty."
        fields["outcome"], fields["email"] = fields["outcome"] or None, fields["email"] or None
        return fields

    def save_story(fields: dict, user_id: int | None = None) -> web.Response:
        cursor = store.db.execute(
            "insert into interview_posts (company, role, round, lang, outcome, text, email, approved, created_at, user_id, questions) "
            "values (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (fields["company"], fields["role"], fields["round"], fields["lang"], fields["outcome"], fields["text"],
             fields["email"], int(time.time()), user_id, json.dumps(fields["questions"], ensure_ascii=False) if fields["questions"] else None))
        return web.json_response({"ok": True, "id": cursor.lastrowid})

    async def interview_submit(request: web.Request) -> web.Response:
        """Interview-experience posts (面经). Anonymous is fine; nothing is public until an admin approves it."""
        if limited(request, f"post:{client(request)}", 5, 3600):
            return fail(429, "Too many attempts. Try again later.")
        fields = story_fields(await request.json())
        return save_story(fields) if isinstance(fields, dict) else fail(422, fields)

    async def device_interview(request: web.Request) -> web.Response:
        """The desktop app shares a story here after a live interview: same review flow, but the
        Bearer token identifies the account (its email is attached for moderation, never shown)."""
        user = device_user(request)
        if not user:
            return fail(401, "Sign in first.")
        if limited(request, f"post:u{user['id']}", 5, 3600):
            return fail(429, "Too many attempts. Try again later.")
        fields = story_fields(await request.json())
        if isinstance(fields, str):
            return fail(422, fields)
        fields["email"] = user["email"]
        return save_story(fields, user["id"])

    async def device_story_audio(request: web.Request) -> web.Response:
        return fail(410, "Recording attachments were removed — stories are text and questions only.")

    async def interview_list(request: web.Request) -> web.Response:
        """The public board: approved posts only, newest first; ?q= filters company/role. Snippets, not full text."""
        q = f"%{request.query.get('q', '').strip()[:60]}%"
        where = "approved = 1" + (" and (company like ? or role like ?)" if q != "%%" else "")
        params = ((q, q) if q != "%%" else ())
        rows = store.db.execute(
            f"select id, company, role, round, lang, outcome, created_at, substr(text, 1, 240) snippet "
            f"from interview_posts where {where} order by created_at desc limit 100", params).fetchall()
        return web.json_response({"posts": [dict(r) for r in rows]})

    async def interview_page(request: web.Request) -> web.Response:
        """One indexable page per post — these are the 'Google 面经' search landings. Rendered from a template
        generated by build_site.py (static/interview-post.html and its /zh copy); only approved posts."""
        zh = request.path.startswith("/zh/")
        try:
            pid = int(request.match_info["id"])
        except ValueError:
            return web.Response(status=404, text="Not found")
        row = store.db.execute("select * from interview_posts where id = ? and approved = 1", (pid,)).fetchone()
        if not row:
            return web.FileResponse(STATIC / "404.html", status=404)
        tpl_path = STATIC / ("zh/interview-post.html" if zh else "interview-post.html")
        if not tpl_path.is_file():  # static build not regenerated yet
            return web.FileResponse(STATIC / ("zh/" if zh else "") / "404.html", status=404)
        e = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")  # noqa: E731
        forwarded_host = request.headers.get("X-Forwarded-Host", "")
        base = site(request) if f"https://{forwarded_host}" not in origins else f"https://{forwarded_host}"  # mirror-served pages keep the mirror's canonical
        label = {"hr": ("HR screen", "HR 初筛"), "oa": ("在线笔试 OA", "在线笔试 OA"), "technical": ("Technical", "技术面"),
                 "system-design": ("System design", "系统设计"), "behavioral": ("Behavioral", "行为面试"),
                 "manager": ("Hiring manager", "主管面"), "onsite": ("Onsite / final", "终面 / 现场面"), "other": ("Other", "其他")}
        outcome = {"offer": ("Offer", "拿到 offer"), "rejected": ("Rejected", "未通过"), "waiting": ("Waiting", "等待结果"),
                   "declined": ("Declined", "婉拒 offer")}.get(row["outcome"] or "", None)
        bits = [time.strftime("%Y-%m-%d", time.gmtime(row["created_at"])), label.get(row["round"], (row["round"],) * 2)[zh],
                {"en": "English", "zh": "中文"}.get(row["lang"], row["lang"])]
        if outcome:
            bits.append(outcome[zh])
        title = (f"{row['role']} · {row['company']} 面经 — Interview Realtime Copilot" if zh
                 else f"{row['role']} interview at {row['company']} — Interview Realtime Copilot")
        try:
            questions = [q for q in json.loads(row["questions"] or "[]")][:20]
        except ValueError:
            questions = []
        questions_html = (f'<div class="card" style="margin-top:16px"><h3 style="margin-top:0">'
                          f'{"被问到的问题" if zh else "Questions they asked"}</h3><ol style="margin:0;padding-left:22px;line-height:1.9">'
                          + "".join(f"<li>{e(q)}</li>" for q in questions) + "</ol></div>") if questions else ""
        meta = {"company": e(row["company"]), "role": e(row["role"]), "title": e(title), "meta": e(" · ".join(bits)),
                "desc": e(row["text"][:155].replace("\n", " ")),
                "body": e(row["text"]).replace("\n", "<br>"), "questions": questions_html,
                "comments": comments_block("story", str(pid), zh)}
        html = tpl_path.read_text()
        for key, value in meta.items():
            html = html.replace(f"{{{{{key.upper()}}}}}", value)
        url = f"{base}/{'zh/' if zh else ''}interviews/{pid}"
        html = re.sub(r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{url}">', html)
        html = re.sub(r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{url}">', html)
        html = re.sub(r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{meta["title"]}">', html)
        html = re.sub(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{meta["desc"]}">', html)
        html = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{meta["desc"]}">', html)
        html = re.sub(r'<title[^>]*>[^<]*</title>', f'<title>{meta["title"]}</title>', html)
        article = json.dumps({"@context": "https://schema.org", "@type": "Article", "headline": title,
                              "datePublished": bits[0], "url": url, "description": row["text"][:155].replace("\n", " ")})
        html = html.replace("</head>", f'<script type="application/ld+json">{article}</script></head>')
        return web.Response(text=html, content_type="text/html")

    def comments_block(post_type: str, post_id: str, zh: bool) -> str:
        """Approved comments plus the submission form, rendered server-side into story and blog pages.
        Comment text is escaped; names are optional and emails are never shown."""
        e = esc_text
        rows = store.db.execute("select name, body, created_at from comments where post_type = ? and post_id = ? and approved = 1 "
                                "order by created_at limit 200", (post_type, post_id)).fetchall()
        items = "".join(f'<div class="comment"><b>{e(r["name"] or ("匿名" if zh else "Anonymous"))}</b>'
                        f' <span class="faint small">{time.strftime("%Y-%m-%d", time.gmtime(r["created_at"]))}</span>'
                        f'<div style="margin-top:4px;white-space:pre-wrap">{e(r["body"])}</div></div>' for r in rows)
        form = (f'<form id="comment-form" data-type="{post_type}" data-id="{e(post_id)}" style="margin-top:18px">'
                f'<div class="inline-form"><input class="input" name="name" maxlength="40" '
                f'placeholder="{"昵称（选填）" if zh else "Name (optional)"}">'
                f'<input class="input" name="email" type="email" maxlength="254" '
                f'placeholder="{"邮箱（选填，不公开）" if zh else "Email (optional, never shown)"}"></div>'
                f'<textarea class="input" name="body" rows="3" maxlength="2000" required style="margin-top:10px" '
                f'placeholder="{"写下你的留言……" if zh else "Your comment…"}"></textarea>'
                f'<button class="btn primary" style="margin-top:10px">{"提交留言" if zh else "Post comment"}</button><p class="error"></p>'
                f'<p class="faint small">{"留言经审核后显示；邮箱不会公开。" if zh else "Comments appear after review; your email is never shown."}</p></form>')
        heading = ("留言" if zh else "Comments") + (f" ({len(rows)})" if rows else "")
        empty = f'<p class="faint small">{"还没有留言——来说第一句。" if zh else "No comments yet — be the first."}</p>'
        return f'<div class="card" style="margin-top:26px"><h3 style="margin-top:0">{e(heading)}</h3>{items or empty}{form}</div>'

    async def comment_submit(request: web.Request) -> web.Response:
        """Visitor comments under stories and blog posts. Anonymous is fine; nothing shows until an admin approves."""
        if limited(request, f"comment:{client(request)}", 8, 3600):
            return fail(429, "Too many attempts. Try again later.")
        body = await request.json()
        post_type, post_id = body.get("type"), str(body.get("id") or "")[:80]
        text = str(body.get("body") or "").strip()
        name = str(body.get("name") or "").strip()[:40] or None
        email = str(body.get("email") or "").strip()[:254] or None
        if post_type == "story":
            try:
                target = store.db.execute("select 1 from interview_posts where id = ? and approved = 1", (int(post_id),)).fetchone()
            except ValueError:
                target = None
        elif post_type == "blog":
            target = store.db.execute("select 1 from blog_posts where slug = ? and published = 1", (post_id,)).fetchone()
        else:
            target = None
        if not target:
            return fail(422, "That page does not exist.")
        if not 2 <= len(text) <= 2000:
            return fail(422, "Write a comment between 2 and 2000 characters.")
        if email and not EMAIL.match(email):
            return fail(422, "Enter a valid email address, or leave it empty.")
        store.db.execute("insert into comments (post_type, post_id, name, body, email, approved, created_at) values (?, ?, ?, ?, ?, 0, ?)",
                         (post_type, post_id, name, text, email, int(time.time())))
        return web.json_response({"ok": True})

    async def blog_list(request: web.Request) -> web.Response:
        """Published posts for the /blog.html index; zh fields are optional and the page falls back to English."""
        rows = [{"slug": r["slug"], "title_en": r["title_en"], "title_zh": r["title_zh"] or "", "created_at": r["created_at"],
                 "snip_en": plain_text(r["body_en"])[:200], "snip_zh": plain_text(r["body_zh"] or "")[:200]}
                for r in store.db.execute("select slug, title_en, title_zh, body_en, body_zh, created_at from blog_posts "
                                          "where published = 1 order by created_at desc limit 100")]
        return web.json_response({"posts": rows})

    async def blog_page(request: web.Request) -> web.Response:
        """One indexable page per published post — admin-written articles, same pattern as the story pages."""
        zh = request.path.startswith("/zh/")
        slug = request.match_info["slug"]
        row = store.db.execute("select * from blog_posts where slug = ? and published = 1", (slug,)).fetchone()
        tpl_path = STATIC / ("zh/blog-post.html" if zh else "blog-post.html")
        if not row or not tpl_path.is_file():
            return web.FileResponse(STATIC / "404.html", status=404)
        e = esc_text
        forwarded_host = request.headers.get("X-Forwarded-Host", "")
        base = site(request) if f"https://{forwarded_host}" not in origins else f"https://{forwarded_host}"  # mirror canonical
        title = (row["title_zh"] or row["title_en"]) if zh else row["title_en"]
        source = (row["body_zh"] or row["body_en"]) if zh else row["body_en"]
        meta = {"title": e(title), "meta": e(time.strftime("%Y-%m-%d", time.gmtime(row["created_at"])) + " · Interview Realtime Copilot"),
                "desc": e(plain_text(source)[:155]), "body": render_markdown(source), "comments": comments_block("blog", slug, zh)}
        html = tpl_path.read_text()
        for key, value in meta.items():
            html = html.replace(f"{{{{{key.upper()}}}}}", value)
        url = f"{base}/{'zh/' if zh else ''}blog/{slug}"
        html = re.sub(r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{url}">', html)
        html = re.sub(r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{url}">', html)
        html = re.sub(r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{meta["title"]}">', html)
        html = re.sub(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{meta["desc"]}">', html)
        html = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{meta["desc"]}">', html)
        html = re.sub(r'<title[^>]*>[^<]*</title>', f'<title>{meta["title"]}</title>', html)
        article = json.dumps({"@context": "https://schema.org", "@type": "Article", "headline": title,
                              "datePublished": time.strftime("%Y-%m-%d", time.gmtime(row["created_at"])),
                              "dateModified": time.strftime("%Y-%m-%d", time.gmtime(row["updated_at"])),
                              "url": url, "description": plain_text(source)[:155],
                              "author": {"@type": "Organization", "name": "Interview Realtime Copilot", "url": origin}})
        html = html.replace("</head>", f'<script type="application/ld+json">{article}</script></head>')
        return web.Response(text=html, content_type="text/html")

    async def posts_sitemap(request: web.Request) -> web.Response:
        """Dynamic sitemap of approved story and published blog URLs — the static sitemap.xml only covers fixed pages.
        Served under whatever host asked (the mirror sends X-Forwarded-Host), so each domain gets its own URLs."""
        day = lambda ts: time.strftime("%Y-%m-%d", time.gmtime(ts))  # noqa: E731
        forwarded_host = request.headers.get("X-Forwarded-Host", "")
        base = site(request) if f"https://{forwarded_host}" not in origins else f"https://{forwarded_host}"
        urls = "".join(f"<url><loc>{base}/{p}interviews/{r[0]}</loc><lastmod>{day(r[1])}</lastmod></url>"
                       for r in store.db.execute("select id, created_at from interview_posts where approved = 1") for p in ("", "zh/"))
        urls += "".join(f"<url><loc>{base}/{p}blog/{r[0]}</loc><lastmod>{day(r[1])}</lastmod></url>"
                        for r in store.db.execute("select slug, updated_at from blog_posts where published = 1") for p in ("", "zh/"))
        return web.Response(text='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                 + urls + "</urlset>", content_type="application/xml")

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
        if path.name in ("interview-post.html", "blog-post.html"):  # {{…}} render templates, not pages
            return web.FileResponse(STATIC / "404.html", status=404)
        if path.is_dir():  # /docs/ → docs/index.html
            path = path / "index.html"
        if STATIC not in path.parents or not path.is_file():
            path = STATIC / "404.html"
            return web.FileResponse(path, status=404)
        return web.FileResponse(path)

    # -- admin dashboard (read-only; accounts flagged with `python -m irc_web.admin make-admin EMAIL`) --
    def admin_only(handler):
        async def wrapped(request: web.Request) -> web.Response:
            user = current(request)
            if not user or not user["is_admin"]:
                return fail(403 if user else 401, "Admins only.")
            return await handler(request)
        return wrapped

    def scalar(sql: str, *params: Any) -> Any:
        return store.db.execute(sql, params).fetchone()[0]

    @admin_only
    async def admin_overview(request: web.Request) -> web.Response:
        now, month = int(time.time()), billing_month()
        users = store.db.execute("select * from users").fetchall()
        allowance = sum(billing.allowance(u) for u in users)
        used = scalar("select coalesce(sum(cost_micro), 0) from usage where month = ?", month)
        credit = scalar("select coalesce(sum(amount_micro), 0) from credit_grants")
        plans: dict[str, int] = {}
        for u in users:
            key = public_user(u)["plan"]
            plans[key] = plans.get(key, 0) + 1
        return web.json_response({
            "month": month,
            "users": {"total": len(users), "new_7d": sum(u["created_at"] > now - 7 * 86400 for u in users),
                      "new_30d": sum(u["created_at"] > now - 30 * 86400 for u in users),
                      "active_30d": scalar("select count(distinct user_id) from usage where ts > ?", now - 30 * 86400),
                      "devices": scalar("select count(*) from device_tokens")},
            "subscriptions": {"plans": plans, "statuses": dict(store.db.execute(
                "select coalesce(status, 'none'), count(*) from users group by 1").fetchall())},
            "usage": {"month_used_usd": used / 1e6, "month_allowance_usd": allowance / 1e6, "credit_usd": max(0, credit) / 1e6,
                      "month_remaining_usd": max(0, allowance - used) / 1e6 + max(0, credit) / 1e6,
                      "month_requests": scalar("select count(*) from usage where month = ?", month),
                      "all_time_used_usd": scalar("select coalesce(sum(cost_micro), 0) from usage") / 1e6,
                      "all_time_requests": scalar("select count(*) from usage"),
                      "audio_minutes_month": round(scalar("select coalesce(sum(audio_input_tokens + audio_output_tokens), 0) from usage where month = ?", month) / 600, 1)},
            "messages": {"wishes": scalar("select count(*) from wishes"), "waitlist": scalar("select count(*) from waitlist")},
        })

    @admin_only
    async def admin_users(request: web.Request) -> web.Response:
        q = f"%{request.query.get('q', '').strip().lower()}%"
        rows = store.db.execute("select * from users where email like ? order by created_at desc limit 500", (q,)).fetchall()
        result = []
        for u in rows:
            summary = billing.summary(u)
            result.append({**public_user(u), "id": u["id"], "created_at": u["created_at"], "used_usd": summary["used_usd"],
                           "allowance_usd": summary["allowance_usd"], "balance_usd": summary["balance_usd"], "credit_usd": summary["credit_usd"],
                           "requests": scalar("select count(*) from usage where user_id = ? and month = ?", u["id"], summary["month"]),
                           "last_active": scalar("select max(last_used_at) from device_tokens where user_id = ?", u["id"]),
                           "devices": scalar("select count(*) from device_tokens where user_id = ?", u["id"])})
        return web.json_response({"users": result})

    STORY_REWARD_USD = 1.00  # roughly thirty minutes of realtime audio — the flywheel bounty for a shared 面经

    @admin_only
    async def admin_interview(request: web.Request) -> web.Response:
        """Approve a post for the public board (or un-approve it), or remove spam entirely.
        Approving a signed-in user's post credits their account once with the story reward."""
        body = await request.json()
        pid = int(body.get("id") or 0)
        if body.get("remove"):
            store.db.execute("delete from interview_posts where id = ?", (pid,))
        else:
            store.db.execute("update interview_posts set approved = ? where id = ?", (1 if body.get("approved") else 0, pid))
            if body.get("approved"):
                post = store.db.execute("select user_id, rewarded from interview_posts where id = ?", (pid,)).fetchone()
                if post and post["user_id"] and not post["rewarded"]:
                    billing.grant(post["user_id"], STORY_REWARD_USD, f"interview-story-{pid}")
                    store.db.execute("update interview_posts set rewarded = 1 where id = ?", (pid,))
        return web.json_response({"ok": True})

    @admin_only
    async def admin_blog(request: web.Request) -> web.Response:
        """Create, update, publish/unpublish or delete blog posts. Bodies are markdown, rendered safely
        (render_markdown escapes all raw HTML)."""
        body = await request.json()
        pid = int(body.get("id") or 0)
        if body.get("remove"):
            row = store.db.execute("select slug from blog_posts where id = ?", (pid,)).fetchone()
            store.db.execute("delete from blog_posts where id = ?", (pid,))
            if row:  # its comments go with it
                store.db.execute("delete from comments where post_type = 'blog' and post_id = ?", (row["slug"],))
            return web.json_response({"ok": True})
        slug = str(body.get("slug") or "").strip().lower()
        fields = (str(body.get("title_en") or "").strip(), str(body.get("title_zh") or "").strip() or None,
                  str(body.get("body_en") or "").strip(), str(body.get("body_zh") or "").strip() or None)
        if not BLOG_SLUG.match(slug):
            return fail(422, "Slug must be 2-80 lowercase letters, digits or dashes.")
        if not fields[0] or not fields[2]:
            return fail(422, "English title and body are required.")
        now = int(time.time())
        try:
            if pid:
                old = store.db.execute("select slug from blog_posts where id = ?", (pid,)).fetchone()
                store.db.execute("update blog_posts set slug = ?, title_en = ?, title_zh = ?, body_en = ?, body_zh = ?, published = ?, "
                                 "updated_at = ? where id = ?", (slug, *fields, 1 if body.get("published") else 0, now, pid))
                if old and old["slug"] != slug:  # comments reference the slug
                    store.db.execute("update comments set post_id = ? where post_type = 'blog' and post_id = ?", (slug, old["slug"]))
            else:
                store.db.execute("insert into blog_posts (slug, title_en, title_zh, body_en, body_zh, published, created_at, updated_at) "
                                 "values (?, ?, ?, ?, ?, ?, ?, ?)", (slug, *fields, 1 if body.get("published") else 0, now, now))
        except sqlite3.IntegrityError:
            return fail(422, "That slug is already taken.")
        return web.json_response({"ok": True})

    @admin_only
    async def admin_comment(request: web.Request) -> web.Response:
        body = await request.json()
        cid = int(body.get("id") or 0)
        if body.get("remove"):
            store.db.execute("delete from comments where id = ?", (cid,))
        else:
            store.db.execute("update comments set approved = ? where id = ?", (1 if body.get("approved") else 0, cid))
        return web.json_response({"ok": True})

    @admin_only
    async def admin_messages(request: web.Request) -> web.Response:
        wishes = [dict(r) for r in store.db.execute("select id, email, text, page, created_at from wishes order by created_at desc limit 500")]
        waitlist = [dict(r) for r in store.db.execute("select email, topic, created_at from waitlist order by created_at desc limit 500")]
        posts = [dict(r) for r in store.db.execute("select id, company, role, round, lang, outcome, email, approved, created_at, text, "
                                                 "rewarded, user_id from interview_posts order by created_at desc limit 500")]
        comments = [dict(r) for r in store.db.execute("select id, post_type, post_id, name, body, email, approved, created_at from comments "
                                                     "order by created_at desc limit 500")]
        blog = [dict(r) for r in store.db.execute("select * from blog_posts order by created_at desc limit 200")]
        return web.json_response({"wishes": wishes, "waitlist": waitlist, "posts": posts, "comments": comments, "blog": blog})

    @admin_only
    async def admin_usage(request: web.Request) -> web.Response:
        since = int(time.time()) - 30 * 86400
        days = store.db.execute("select strftime('%Y-%m-%d', ts, 'unixepoch') d, count(*) n, sum(cost_micro) c, count(distinct user_id) u "
                                "from usage where ts > ? group by d order by d", (since,)).fetchall()
        models = store.db.execute("select model, count(*) n, sum(cost_micro) c from usage where month = ? group by model order by c desc",
                                  (billing_month(),)).fetchall()
        return web.json_response({"days": [{"day": d, "requests": n, "usd": c / 1e6, "users": u} for d, n, c, u in days],
                                  "models": [{"model": m, "requests": n, "usd": c / 1e6} for m, n, c in models]})

    @admin_only
    async def admin_traffic(request: web.Request) -> web.Response:
        since = int(time.time()) - 30 * 86400
        rows = lambda sql: [list(r) for r in store.db.execute(sql, (since,))]
        totals = dict(store.db.execute("select kind, count(*) from events where ts > ? group by kind", (since,)).fetchall())
        return web.json_response({
            "totals": {"views": totals.get("view", 0), "downloads": totals.get("download", 0), "signups_tracked": totals.get("signup", 0),
                       "signups": scalar("select count(*) from users where created_at > ?", since),
                       "subscribers": scalar("select count(*) from users where status in ('active', 'trialing')")},
            "days": rows("select strftime('%Y-%m-%d', ts, 'unixepoch') d, sum(kind = 'view'), sum(kind = 'download'), sum(kind = 'signup') "
                         "from events where ts > ? group by d order by d"),
            "sources": rows("select source, sum(kind = 'view'), sum(kind = 'download'), sum(kind = 'signup') from events where ts > ? "
                            "group by source order by 2 desc limit 30"),
            "pages": rows("select page, count(*) from events where ts > ? and kind = 'view' group by page order by 2 desc limit 20"),
        })

    app = web.Application(middlewares=[guard], client_max_size=64 * 1024 * 1024)  # transcription uploads
    app["db_path"] = db_path or os.environ.get("IRC_WEB_DB", "irc-web.sqlite3")
    relay.setup(app, billing, origin, openai_upstream or os.environ.get("IRC_OPENAI_UPSTREAM", "https://api.openai.com"), device_user)
    app.add_routes([
        web.post("/api/v1/auth/{action:register|login}", device_auth), web.post("/api/v1/auth/logout", device_logout),
        web.get("/api/v1/me", device_me), web.post("/api/v1/auth/web-link", web_link), web.get("/auth/link", redeem_link),
        web.post("/api/v1/interviews", device_interview),
        web.post("/api/signup", signup), web.post("/api/login", login), web.post("/api/logout", logout),
        web.get("/api/me", me), web.post("/api/checkout", checkout), web.post("/api/portal", portal),
        web.post("/api/waitlist", waitlist), web.post("/api/wish", wish),
        web.post("/api/interviews", interview_submit), web.get("/api/interviews", interview_list),
        web.get("/zh/interviews/{id}", interview_page), web.get("/interviews/{id}", interview_page),
        web.get("/api/blog", blog_list), web.post("/api/comments", comment_submit),
        web.get("/zh/blog/{slug}", blog_page), web.get("/blog/{slug}", blog_page),
        web.get("/sitemap-posts.xml", posts_sitemap),
        web.post("/api/v1/interviews/audio/{id}", device_story_audio),  # retired — kept so old app builds get a clear 410
        web.post("/api/track", track), web.get("/api/admin/traffic", admin_traffic),
        web.get("/api/admin/overview", admin_overview), web.get("/api/admin/users", admin_users),
        web.get("/api/admin/messages", admin_messages), web.get("/api/admin/usage", admin_usage), web.post("/api/stripe/webhook", webhook),
        web.post("/api/admin/interview", admin_interview),
        web.post("/api/admin/blog", admin_blog), web.post("/api/admin/comment", admin_comment),
        web.get("/", page), web.get("/{name:.+}", page),
    ])
    return app


def main() -> None:
    web.run_app(build_app(), host=os.environ.get("IRC_WEB_HOST", "127.0.0.1"), port=int(os.environ.get("IRC_WEB_PORT", "8090")))


if __name__ == "__main__":
    main()
