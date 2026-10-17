"""When each subscription's login ends, and whose it is.

Every provider's subscriptions are asked through their harness's adapter, `login-end`: one
JSON object, `email` (whose login it is) and `ends` (the epoch second it stops serving, after
which only a new login brings it back; null where the harness writes no such day down).  The
answers are kept in `state/logins.json` as {provider: {account: {email, ends, checked_at}}},
for every screen and reminder that warns before a login ends.  The tick asks each one at
most once an hour, since a login's end moves only when somebody logs in again; whoever saw
that happen asks for that one at once with `force`.
"""

import json
import os
import subprocess
import time

from . import config

ASK_EVERY = 3600    # seconds an answer stands before the tick asks again
ASK_TIMEOUT = 20    # the verb reads files on this machine; one that hangs answers nothing


def path():
    return config.STATE / "logins.json"


def read():
    """{provider: {account: {email, ends, checked_at}}} as last asked; {} when nothing is."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _ask(harness, account):
    """The adapter's {email, ends} for that account's login, or None when it said nothing
    usable: no such verb, a failure, a timeout, or anything but that object."""
    try:
        proc = subprocess.run([str(config.adapter(harness)), "login-end"],
                              capture_output=True, encoding="utf-8", errors="replace",
                              env={**os.environ, **config.account_env(account)},
                              timeout=ASK_TIMEOUT)
        data = json.loads(proc.stdout) if proc.returncode == 0 else None
    except (config.Error, subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    email, ends = data.get("email"), data.get("ends")
    if email is not None and not (isinstance(email, str) and email):
        return None
    if ends is not None and (isinstance(ends, bool) or not isinstance(ends, (int, float))):
        return None
    return {"email": email, "ends": ends}


def refresh(cfg, now=None, force=()):
    """Ask every subscription the config lists whose answer is older than ASK_EVERY, or is
    named in `force` as (provider, account), and keep what they said; returns what is kept.

    An adapter that answers nothing leaves its last answer standing, so a briefly unrunnable
    one neither raises a warning nor lifts one.  A subscription the config no longer lists is
    dropped with its answer.
    """
    now = time.time() if now is None else now
    old, kept = read(), {}
    for provider in cfg["providers"]:
        try:
            harness, _ = config.provider_harness(cfg, provider)
        except config.Error:
            continue     # a provider whose models were all removed has no login to ask about
        for account in config.accounts(cfg, provider) or [config.DEFAULT_ACCOUNT]:
            last = (old.get(provider) or {}).get(account)
            checked = last.get("checked_at") if isinstance(last, dict) else None
            fresh = (isinstance(checked, (int, float)) and (provider, account) not in force
                     and 0 <= now - checked < ASK_EVERY)
            answer = None if fresh else _ask(harness, account)
            if answer is not None:
                kept.setdefault(provider, {})[account] = {**answer, "checked_at": now}
            elif isinstance(last, dict):
                kept.setdefault(provider, {})[account] = last
    if kept != old:
        config._write_json(path(), kept)
    return kept
