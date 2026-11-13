import hashlib
import hmac
import json
import time

import pytest
from aiohttp import web

from irc_web.app import build_app, verify_stripe_signature

ORIGIN = "http://localhost:8090"


@pytest.fixture
async def site(aiohttp_client, tmp_path, monkeypatch):
    calls = []

    async def stripe_fake(request):  # a minimal Stripe API
        calls.append((request.path, dict(await request.post())))
        if request.path == "/v1/checkout/sessions":
            return web.json_response({"url": "https://checkout.stripe.test/s/1"})
        return web.json_response({"url": "https://billing.stripe.test/p/1"})

    stripe = web.Application()
    stripe.router.add_post("/v1/checkout/sessions", stripe_fake)
    stripe.router.add_post("/v1/billing_portal/sessions", stripe_fake)
    stripe_client = await aiohttp_client(stripe)
    monkeypatch.setenv("IRC_WEB_ORIGIN", ORIGIN)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    client = await aiohttp_client(build_app(db_path=str(tmp_path / "db.sqlite3"), stripe_api=str(stripe_client.make_url("")).rstrip("/")))
    client.stripe_calls = calls
    return client


def post(client, path, body=None, **headers):
    return client.post(path, json=body or {}, headers={"Origin": ORIGIN, **headers})


def signed(payload: bytes, secret="whsec_test"):
    t = int(time.time())
    return f"t={t},v1=" + hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()


async def test_pages_are_served(site):
    for path in ("/", "/use-cases.html", "/pricing.html", "/demo.html", "/download.html", "/login.html", "/account.html", "/i18n.js"):
        response = await site.get(path)
        assert response.status == 200, path
    assert (await site.get("/../app.py")).status == 404


async def test_signup_login_logout_and_rules(site):
    assert (await post(site, "/api/signup", {"email": "bad", "password": "long-enough-1"})).status == 422
    assert (await post(site, "/api/signup", {"email": "a@example.com", "password": "short"})).status == 422
    response = await post(site, "/api/signup", {"email": "A@Example.com", "password": "long-enough-1"})
    assert response.status == 200 and (await response.json())["user"]["plan"] == "free"
    assert (await post(site, "/api/signup", {"email": "a@example.com", "password": "long-enough-1"})).status == 409
    me = await (await site.get("/api/me")).json()
    assert me["user"]["email"] == "a@example.com" and me["payments"] is True
    await post(site, "/api/logout")
    assert (await (await site.get("/api/me")).json())["user"] is None
    assert (await post(site, "/api/login", {"email": "a@example.com", "password": "wrong-password"})).status == 401
    assert (await post(site, "/api/login", {"email": "a@example.com", "password": "long-enough-1"})).status == 200


async def test_cross_site_posts_are_refused(site):
    response = await site.post("/api/signup", json={"email": "a@example.com", "password": "long-enough-1"}, headers={"Origin": "https://evil.test"})
    assert response.status == 403


async def test_checkout_webhook_and_portal(site):
    assert (await post(site, "/api/checkout", {"plan": "monthly"})).status == 401
    await post(site, "/api/signup", {"email": "b@example.com", "password": "long-enough-1"})
    response = await post(site, "/api/checkout", {"plan": "yearly"})
    assert (await response.json())["url"].startswith("https://checkout.stripe.test")
    _, form = site.stripe_calls[-1]
    assert form["mode"] == "subscription" and form["line_items[0][price_data][unit_amount]"] == "19900"
    assert form["line_items[0][price_data][recurring][interval]"] == "year"
    user_id = form["client_reference_id"]
    event = json.dumps({"id": "evt_1", "type": "checkout.session.completed",
                        "data": {"object": {"client_reference_id": user_id, "customer": "cus_1", "metadata": {"plan": "yearly"}}}}).encode()
    assert (await site.post("/api/stripe/webhook", data=event, headers={"Stripe-Signature": "t=1,v1=bad"})).status == 400
    assert (await site.post("/api/stripe/webhook", data=event, headers={"Stripe-Signature": signed(event)})).status == 200
    assert (await site.post("/api/stripe/webhook", data=event, headers={"Stripe-Signature": signed(event)})).status == 200  # replay is idempotent
    user = (await (await site.get("/api/me")).json())["user"]
    assert user["plan"] == "yearly" and user["status"] == "active"
    cancel = json.dumps({"id": "evt_2", "type": "customer.subscription.deleted", "data": {"object": {"customer": "cus_1", "status": "canceled"}}}).encode()
    await site.post("/api/stripe/webhook", data=cancel, headers={"Stripe-Signature": signed(cancel)})
    assert (await (await site.get("/api/me")).json())["user"]["plan"] == "free"
    assert (await (await post(site, "/api/portal")).json())["url"].startswith("https://billing.stripe.test")


async def test_waitlist(site):
    assert (await post(site, "/api/waitlist", {"email": "c@example.com", "topic": "windows"})).status == 200
    assert (await post(site, "/api/waitlist", {"email": "nope"})).status == 422


def test_signature_rejects_old_or_wrong():
    payload = b"{}"
    assert not verify_stripe_signature(payload, signed(payload, "other"), "whsec_test")
    old = int(time.time()) - 3600
    header = f"t={old},v1=" + hmac.new(b"whsec_test", f"{old}.".encode() + payload, hashlib.sha256).hexdigest()
    assert not verify_stripe_signature(payload, header, "whsec_test")
