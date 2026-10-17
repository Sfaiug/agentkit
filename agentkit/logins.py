"""When each subscription's login ends, and whose it is.

Every provider's subscriptions are asked through their harness's adapter, `login-end`: one
JSON object, `email` (whose login it is) and `ends` (the epoch second it stops serving, after
which only a new login brings it back; null where the harness writes no such day down).  The
answers are kept in `state/logins.json` as {provider: {account: {email, ends, checked_at}}},
for every screen and reminder that warns before a login ends.  The tick asks each one at
most once an hour, answered or not, since a login's end moves only when somebody logs in
again; whoever saw that happen asks for that one alone at once with `force`.
"""

from datetime import date
import json
import os
import signal
import subprocess
import time

from . import config, menu, notify

ASK_EVERY = 3600    # seconds after an ask before the tick asks again
ASK_TIMEOUT = 20    # the verb reads files on this machine; one that hangs answers nothing
REMIND_WITHIN = 3 * 86400   # how near its end a login pages the owner, once a local day
WARN_WITHIN = 7 * 86400     # ... and turns its meter on the ak screen amber


def path():
    return config.STATE / "logins.json"


def read():
    """{provider: {account: {email, ends, checked_at}}}: email and ends as last answered (absent
    until one is), checked_at when last asked; {} when nothing is."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _ask(harness, account):
    """The adapter's {email, ends} for that account's login, or None when it said nothing
    usable: no such verb, a failure, a timeout, or anything but that object."""
    try:
        with subprocess.Popen([str(config.adapter(harness)), "login-end"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace",
                              env={**os.environ, **config.account_env(account)},
                              start_new_session=True) as proc:
            try:
                out = proc.communicate(timeout=ASK_TIMEOUT)[0]
            except BaseException:
                # Hung or interrupted, its readers (security, jq) die with it rather than pile up
                # a tick at a time: in their own session no ^C reaches them.  Their output
                # closes as they die; the ones a subreaper caller adopted, it reaps here, or
                # they could still be exiting once the ask has returned.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.communicate(timeout=ASK_TIMEOUT)
                    while True:
                        os.waitpid(-proc.pid, 0)
                except (ProcessLookupError, ChildProcessError, subprocess.TimeoutExpired):
                    pass    # all gone, or one left the group still holding the output
                raise
        data = json.loads(out) if proc.returncode == 0 else None
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
    """Ask every subscription the config lists that was last asked ASK_EVERY ago or more or,
    given `force` as (provider, account) pairs, those alone, and keep what they said; returns
    what is kept.  Each is asked through the harness it logs in with
    (config.provider_harnesses), so the one a sign-in ran answers for it.

    An adapter that answers nothing, or a provider no harness names, leaves its last answer
    standing, so a briefly unrunnable one neither raises a warning nor lifts one.  An answer
    another refresh kept since this one read the file stands unless this one asked later: a
    sign-in's, made while the tick still asked the old login, is not undone by the tick's.  A
    subscription the config no longer lists is dropped with its answer.
    """
    now = time.time() if now is None else now
    old, kept, asked = read(), {}, set()
    for provider in cfg["providers"]:
        harness = next(iter(config.provider_harnesses(cfg, provider)), None)
        for account in config.accounts(cfg, provider) or [config.DEFAULT_ACCOUNT]:
            last = (old.get(provider) or {}).get(account)
            last = last if isinstance(last, dict) else {}
            checked = last.get("checked_at")
            fresh = ((provider, account) not in force if force else
                     isinstance(checked, (int, float)) and 0 <= now - checked < ASK_EVERY)
            if not fresh:
                asked.add((provider, account))
            kept.setdefault(provider, {})[account] = last if fresh else {
                **last, **(harness and _ask(harness, account) or {}), "checked_at": now}
    config.ensure_dirs()
    with config._record_lock(path()):
        on_disk = read()
        for provider, accounts in kept.items():
            for account in accounts:
                theirs = (on_disk.get(provider) or {}).get(account)
                if not isinstance(theirs, dict) or theirs == (old.get(provider) or {}).get(account):
                    continue    # nobody kept another answer since
                if (provider, account) not in asked or theirs.get("checked_at", now) > now:
                    accounts[account] = theirs
        if kept != on_disk:
            config._write_json(path(), kept, prepare=False)
    return kept


def remind(cfg, now=None):
    """Refresh, then page the owner once per subscription and local calendar day while its
    login ends within REMIND_WITHIN or has ended: `Claude II login owner@acme.test ends Mon 26
    Oct 04:47 (in 2 days). Log in again from ak.`  The day is in the page's key, so no tick or
    restart pages twice; a new login moves `ends` past the window, or to null, and it stops,
    a page the webhook has not taken yet with it, since only asking again retries one."""
    now = time.time() if now is None else now
    for provider, accounts in refresh(cfg, now).items():
        for account, login in accounts.items():
            when = ending(login, now, REMIND_WITHIN)
            if not when:
                continue
            label = config.account_label(cfg, provider, account,
                                         menu.NAMES.get(provider, provider.title()))
            whose = f" {login['email']}" if login.get("email") else ""
            notify.page(f"login:{provider}:{account}:{date.fromtimestamp(now)}", label,
                        f"{label} login{whose} {when}. Log in again from ak.")


def ending(login, now, within=WARN_WITHIN):
    """When `login`, one of `read`'s, ends -- `ends Mon 26 Oct 04:47 (in 2 days)`, or `ended
    Mon 26 Oct 04:47` -- while that is `within` seconds away or past; None for one further
    off or with no end written down."""
    ends = login.get("ends") if isinstance(login, dict) else None
    if not isinstance(ends, (int, float)) or ends - now > within:
        return None
    at = time.strftime("%a %d %b %H:%M", time.localtime(ends))
    days = (date.fromtimestamp(ends) - date.fromtimestamp(now)).days
    soon = {0: "today", 1: "tomorrow"}.get(days, f"in {days} days")
    return f"ended {at}" if ends <= now else f"ends {at} ({soon})"
