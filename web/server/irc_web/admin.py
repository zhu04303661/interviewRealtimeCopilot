"""Server administration (run on the server as the service user, with /etc/irc-web.env loaded):

    python -m irc_web.admin set-openai-key          # reads the key from stdin (not echoed); stored encrypted
    python -m irc_web.admin grant EMAIL USD [REASON] # add credit to an account
    python -m irc_web.admin usage [EMAIL]            # this month's usage
    python -m irc_web.admin make-admin EMAIL         # let a website account open /admin.html (remove-admin EMAIL to undo)
    python -m irc_web.admin set-price MODEL_PREFIX INPUT CACHED OUTPUT AUDIO_IN AUDIO_OUT [PER_MINUTE]  # USD per 1M tokens
"""

from __future__ import annotations

import getpass
import os
import sqlite3
import sys

from .app import Store
from .billing import Billing, month_key


def main(argv: list[str]) -> None:
    store = Store(os.environ.get("IRC_WEB_DB", "irc-web.sqlite3"))
    billing = Billing(store.db)
    command, *args = argv or ["help"]
    if command == "set-openai-key":
        key = (getpass.getpass("OpenAI API key: ") if sys.stdin.isatty() else sys.stdin.readline()).strip()
        if not key.startswith("sk-"):
            raise SystemExit("That does not look like an OpenAI API key.")
        billing.set_openai_key(key)
        print("Stored (encrypted).")
    elif command == "grant":
        user = store.user_by_email(args[0].lower()) or sys.exit("No such account.")
        billing.grant(user["id"], float(args[1]), args[2] if len(args) > 2 else "manual")
        print(billing.summary(user))
    elif command == "usage":
        where, params = ("where u.email = ?", (args[0].lower(),)) if args else ("", ())
        rows = store.db.execute(f"select u.email, count(g.id) n, coalesce(sum(g.cost_micro), 0) c from users u left join usage g on g.user_id = u.id "
                                f"and g.month = ? {where} group by u.id order by c desc", (month_key(), *params)).fetchall()
        for row in rows:
            print(f"{row['email']:40} {row['n']:6} requests  ${row['c'] / 1e6:.4f}")
    elif command in ("make-admin", "remove-admin"):
        user = store.user_by_email(args[0].lower()) or sys.exit("No such account: register it on the website first.")
        store.db.execute("update users set is_admin = ? where id = ?", (int(command == "make-admin"), user["id"]))
        print(f"{user['email']}: admin {'granted' if command == 'make-admin' else 'removed'}.")
    elif command == "set-price":
        values = [float(v) for v in args[1:7]] + ([0.0] if len(args) < 8 else [float(args[7])])
        store.db.execute("insert or replace into prices values (?, ?, ?, ?, ?, ?, ?)", (args[0], *values[:6]))
        print("Saved.")
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (IndexError, ValueError, sqlite3.Error) as error:
        raise SystemExit(f"{error}\n{__doc__}") from error
