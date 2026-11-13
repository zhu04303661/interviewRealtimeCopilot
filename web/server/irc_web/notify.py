"""Email notifications to the team (e.g. a new notify-me sign-up), sent over SMTP in a background thread.

Configuration (environment): IRC_SMTP_HOST, IRC_SMTP_PORT (587, STARTTLS; 465 = implicit TLS),
IRC_SMTP_USER, IRC_SMTP_PASSWORD, IRC_SMTP_FROM (defaults to the user), IRC_NOTIFY_TO (the support inbox).
Without IRC_SMTP_HOST nothing is sent; the sign-up is still stored in the database.
"""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("irc_web.notify")


def configured() -> bool:
    return bool(os.environ.get("IRC_SMTP_HOST") and os.environ.get("IRC_NOTIFY_TO"))


def _send(subject: str, body: str, reply_to: str | None) -> None:
    host, port = os.environ["IRC_SMTP_HOST"], int(os.environ.get("IRC_SMTP_PORT", "587"))
    user, password = os.environ.get("IRC_SMTP_USER", ""), os.environ.get("IRC_SMTP_PASSWORD", "")
    message = EmailMessage()
    message["From"] = os.environ.get("IRC_SMTP_FROM") or user
    message["To"] = os.environ["IRC_NOTIFY_TO"]
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(body)
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls(context=context)
            if user:
                smtp.login(user, password)
            smtp.send_message(message)


async def notify(subject: str, body: str, reply_to: str | None = None) -> bool:
    """Send one notification; failures are logged, never raised (the visitor's request already succeeded)."""
    if not configured():
        return False
    try:
        await asyncio.to_thread(_send, subject, body, reply_to)
        return True
    except (OSError, smtplib.SMTPException) as error:
        log.warning("notification email failed: %s", error)
        return False
