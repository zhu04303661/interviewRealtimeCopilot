"""Usage metering, monthly allowances, credit balance, device tokens and the stored OpenAI key.

Money is kept in micro-dollars (1e-6 USD). A model price "per 1M tokens in USD"
is therefore exactly the cost of one token in micro-dollars.

Each calendar month (UTC) an account gets an allowance by plan (free or Pro).
Usage is taken from the allowance first, then from purchased/granted credit.
Requests are refused (HTTP 402) when allowance and credit are both used up.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

SCHEMA = """
create table if not exists device_tokens (hash text primary key, user_id integer not null, name text not null,
  created_at integer not null, last_used_at integer);
create table if not exists web_links (code_hash text primary key, user_id integer not null, expires_at integer not null);
create table if not exists usage (id integer primary key, user_id integer not null, ts integer not null, month text not null,
  model text not null, endpoint text not null, input_tokens integer not null default 0, cached_tokens integer not null default 0,
  output_tokens integer not null default 0, audio_input_tokens integer not null default 0, audio_output_tokens integer not null default 0,
  seconds real not null default 0, cost_micro integer not null);
create index if not exists usage_user_month on usage (user_id, month);
create table if not exists credit_grants (id integer primary key, user_id integer not null, amount_micro integer not null,
  reason text not null, created_at integer not null);
create table if not exists provider_keys (id integer primary key, provider text not null, ciphertext blob not null,
  created_at integer not null, active integer not null default 1);
create table if not exists prices (model_prefix text primary key, input real not null, cached_input real not null, output real not null,
  audio_input real not null, audio_output real not null, per_minute real not null default 0);
"""

# USD per 1M tokens (and per minute for duration-billed transcription). Longest matching prefix wins; "" is the default.
# These are starting values: confirm them against OpenAI's current price list and adjust with `irc_web.admin set-price`.
DEFAULT_PRICES = {
    "": (1.25, 0.125, 10.0, 1.25, 10.0, 0.0),
    "gpt-realtime": (4.0, 0.4, 16.0, 32.0, 64.0, 0.0),
    "gpt-4o-transcribe": (2.5, 2.5, 10.0, 6.0, 6.0, 0.006),
    "gpt-4o-mini-transcribe": (1.25, 1.25, 5.0, 3.0, 3.0, 0.003),
    "gpt-live": (4.0, 0.4, 16.0, 32.0, 64.0, 0.0),
}


def month_key(ts: float | None = None) -> str:
    return time.strftime("%Y-%m", time.gmtime(ts or time.time()))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Allowances:
    free_micro: int
    pro_micro: int

    @classmethod
    def from_environment(cls) -> Allowances:
        return cls(int(float(os.environ.get("IRC_FREE_ALLOWANCE_USD", "1")) * 1e6),
                   int(float(os.environ.get("IRC_PRO_ALLOWANCE_USD", "20")) * 1e6))


class Billing:
    def __init__(self, db: sqlite3.Connection, allowances: Allowances | None = None, secret: str | None = None) -> None:
        self.db = db
        self.db.executescript(SCHEMA)
        if not self.db.execute("select 1 from prices limit 1").fetchone():
            self.db.executemany("insert into prices values (?, ?, ?, ?, ?, ?, ?)", [(k, *v) for k, v in DEFAULT_PRICES.items()])
        self.allowances = allowances or Allowances.from_environment()
        secret = secret if secret is not None else os.environ.get("IRC_WEB_SECRET", "")
        self._fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())) if secret else None

    # -- device tokens -------------------------------------------------------
    def issue_token(self, user_id: int, name: str) -> str:
        token = "irc_" + secrets.token_urlsafe(32)
        self.db.execute("insert into device_tokens values (?, ?, ?, ?, null)", (token_hash(token), user_id, name[:80] or "device", int(time.time())))
        return token

    def user_for_token(self, token: str) -> sqlite3.Row | None:
        digest = token_hash(token)
        user = self.db.execute("select u.* from users u join device_tokens d on d.user_id = u.id where d.hash = ?", (digest,)).fetchone()
        if user:
            self.db.execute("update device_tokens set last_used_at = ? where hash = ?", (int(time.time()), digest))
        return user

    def revoke_token(self, token: str) -> None:
        self.db.execute("delete from device_tokens where hash = ?", (token_hash(token),))

    def issue_web_link(self, user_id: int) -> str:
        code = secrets.token_urlsafe(24)
        self.db.execute("insert into web_links values (?, ?, ?)", (token_hash(code), user_id, int(time.time()) + 120))
        return code

    def redeem_web_link(self, code: str) -> int | None:
        row = self.db.execute("delete from web_links where code_hash = ? and expires_at > ? returning user_id", (token_hash(code), int(time.time()))).fetchone()
        return row[0] if row else None

    # -- OpenAI key ----------------------------------------------------------
    def set_openai_key(self, key: str) -> None:
        if not self._fernet:
            raise RuntimeError("IRC_WEB_SECRET must be set to store provider keys.")
        self.db.execute("update provider_keys set active = 0 where provider = 'openai'")
        self.db.execute("insert into provider_keys (provider, ciphertext, created_at) values ('openai', ?, ?)",
                        (self._fernet.encrypt(key.encode()), int(time.time())))

    def openai_key(self) -> str | None:
        row = self.db.execute("select ciphertext from provider_keys where provider = 'openai' and active = 1 order by id desc limit 1").fetchone()
        if row and self._fernet:
            try:
                return self._fernet.decrypt(row[0]).decode()
            except InvalidToken:
                return None
        return os.environ.get("OPENAI_API_KEY") or None

    # -- prices and metering --------------------------------------------------
    def price(self, model: str) -> sqlite3.Row:
        rows = self.db.execute("select * from prices").fetchall()
        return max((r for r in rows if model.startswith(r["model_prefix"])), key=lambda r: len(r["model_prefix"]))

    def cost(self, model: str, usage: dict[str, Any]) -> tuple[int, dict[str, float]]:
        """Cost in micro-dollars of one OpenAI usage object (Responses, Realtime or transcription shape)."""
        p = self.price(model)
        if usage.get("type") == "duration":
            seconds = float(usage.get("seconds") or 0)
            return round(seconds / 60 * p["per_minute"] * 1e6), {"seconds": seconds}
        inp = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        out = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        in_d = usage.get("input_tokens_details") or usage.get("input_token_details") or {}
        out_d = usage.get("output_tokens_details") or usage.get("output_token_details") or {}
        cached = int(in_d.get("cached_tokens") or 0)
        audio_in = int(in_d.get("audio_tokens") or 0)
        audio_out = int(out_d.get("audio_tokens") or 0)
        text_in = max(0, inp - audio_in - cached)
        text_out = max(0, out - audio_out)
        micro = text_in * p["input"] + cached * p["cached_input"] + audio_in * p["audio_input"] + text_out * p["output"] + audio_out * p["audio_output"]
        return round(micro), {"input_tokens": inp, "cached_tokens": cached, "output_tokens": out, "audio_input_tokens": audio_in, "audio_output_tokens": audio_out}

    def allowance(self, user: sqlite3.Row) -> int:
        pro = user["status"] in ("active", "trialing") and user["plan"] in ("monthly", "yearly")
        return self.allowances.pro_micro if pro else self.allowances.free_micro

    def used(self, user_id: int, month: str | None = None) -> int:
        return self.db.execute("select coalesce(sum(cost_micro), 0) from usage where user_id = ? and month = ?", (user_id, month or month_key())).fetchone()[0]

    def summary(self, user: sqlite3.Row) -> dict[str, Any]:
        allowance, used = self.allowance(user), self.used(user["id"])
        credit = self.db.execute("select coalesce(sum(amount_micro), 0) from credit_grants where user_id = ?", (user["id"],)).fetchone()[0]
        remaining = max(0, allowance - used) + max(0, credit)
        return {"month": month_key(), "allowance_usd": allowance / 1e6, "used_usd": round(used / 1e6, 4), "credit_usd": round(max(0, credit) / 1e6, 4),
                "balance_usd": round(remaining / 1e6, 4), "used_percent": min(100, round(used / allowance * 100)) if allowance else 100}

    def balance_micro(self, user: sqlite3.Row) -> int:
        credit = self.db.execute("select coalesce(sum(amount_micro), 0) from credit_grants where user_id = ?", (user["id"],)).fetchone()[0]
        return max(0, self.allowance(user) - self.used(user["id"])) + max(0, credit)

    def record(self, user: sqlite3.Row, model: str, endpoint: str, usage: dict[str, Any]) -> int:
        """Meter one usage object; usage beyond the monthly allowance is debited from credit. Returns the cost."""
        cost, parts = self.cost(model, usage)
        before = max(0, self.allowance(user) - self.used(user["id"]))
        self.db.execute("insert into usage (user_id, ts, month, model, endpoint, input_tokens, cached_tokens, output_tokens, audio_input_tokens,"
                        " audio_output_tokens, seconds, cost_micro) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (user["id"], int(time.time()), month_key(), model[:80], endpoint[:80], parts.get("input_tokens", 0), parts.get("cached_tokens", 0),
                         parts.get("output_tokens", 0), parts.get("audio_input_tokens", 0), parts.get("audio_output_tokens", 0), parts.get("seconds", 0), cost))
        if cost > before:
            self.db.execute("insert into credit_grants (user_id, amount_micro, reason, created_at) values (?, ?, 'overflow', ?)",
                            (user["id"], -(cost - before), int(time.time())))
        return cost

    def grant(self, user_id: int, usd: float, reason: str) -> None:
        self.db.execute("insert into credit_grants (user_id, amount_micro, reason, created_at) values (?, ?, ?, ?)",
                        (user_id, round(usd * 1e6), reason, int(time.time())))
