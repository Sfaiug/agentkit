"""When each subscription's login ends, and whose it is.

Every provider's subscriptions are asked through their harness's adapter, `login-end`: one
JSON object, `email` (whose login it is) and `ends` (the epoch second it stops serving, after
which only a new login brings it back; null where the harness writes no such day down).  The
answers are kept in `state/logins.json` as {provider: {account: {email, ends, checked_at}}},
for every screen and reminder that warns before a login ends.  The tick asks each one at
most once an hour, answered or not, since a login's end moves only when somebody logs in
again; but one whose meter is amber (`ending`) every time it runs, so a new login made
elsewhere shows on the ak screen at the next tick.  One made from the ak screen is asked as it
closes (`refresh`'s `renewed`), so its meter turns back at once.
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


def harness(cfg, provider):
    """The harness that asks and signs in `provider`'s logins: its first model's, else the one
    the shipped default runs it on, so a login whose models were all removed is still asked;
    None where neither names one."""
    return next(iter(config.provider_harnesses(cfg, provider)), None)


def refresh(cfg, now=None, renewed=None):
    """Ask every subscription the config lists that was last asked ASK_EVERY ago or more, or
    whose login ends within WARN_WITHIN or has ended, and keep what they said; returns what
    is kept.  `renewed`, the (provider, account) of a login just made afresh, is asked alone,
    whenever it was last.

    An adapter that answers nothing, or a provider no harness names, leaves its last answer
    standing, so a briefly unrunnable one neither raises a warning nor lifts one.  A
    subscription the config no longer lists is dropped with its answer.
    """
    now = time.time() if now is None else now
    old, kept = read(), {}
    for provider in cfg["providers"]:
        asker = harness(cfg, provider)
        for account in config.accounts(cfg, provider) or [config.DEFAULT_ACCOUNT]:
            last = (old.get(provider) or {}).get(account)
            last = last if isinstance(last, dict) else {}
            checked = last.get("checked_at")
            fresh = (renewed != (provider, account) if renewed else
                     isinstance(checked, (int, float)) and 0 <= now - checked < ASK_EVERY
                     and not ending(last, now))
            kept.setdefault(provider, {})[account] = last if fresh else {
                **last, **(asker and _ask(asker, account) or {}), "checked_at": now}
    if kept != old:
        config.ensure_dirs()
        with config._record_lock(path()):
            # The tick and the ak screen, for a login just made there, can refresh at once: an
            # answer written since this one read stands unless this one asked it later.
            standing = read()
            for provider, accounts in kept.items():
                for account, login in accounts.items():
                    theirs = (standing.get(provider) or {}).get(account)
                    if (isinstance(theirs, dict) and theirs != (old.get(provider) or {}).get(account)
                            and _asked(theirs) >= _asked(login)):
                        accounts[account] = theirs
            config._write_json(path(), kept, prepare=False)
    return kept


def _asked(login):
    """When `login`, one of `read`'s, was last asked; -inf for one never asked."""
    checked = login.get("checked_at")
    return checked if isinstance(checked, (int, float)) else float("-inf")


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
            notify.page(f"login:{provider}:{account}:{date.fromtimestamp(now)}", f"{label} login",
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
