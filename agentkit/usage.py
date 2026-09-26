"""Subscription meters, budget, and the model pick order.

budget = (fraction left + the resets in hand) / fraction of the window left, taking the minimum
across the model's non-session gate meters. Above 1 means slack to spend; below 1 means ahead of
pace. The workers rank highest budget first, unknown last. A provider the harness reports no
meter for at all (`[usage] none`) is neutral at 1.0, ranked by the same rules and never last;
only a failed probe is unknown. A reset in hand is one whole weekly
allowance, exactly as headroom counts it, so the provider holding a spare week is drained first
and every subscription runs out at the same moment.
When Fable's scoped allowance lags the shared week, prefer it as executor with a legal reviewer
that has headroom. Opus still ranks on its real meters, so the gap never parks it.

pace = used% - elapsed% of the meter's window.  Positive means burning faster than the window
refills.  A provider's pace is the max over its meters.  It no longer ranks anything: pace_margin
decides one thing, when a payg provider is allowed in, and it never withholds a model from
anything.

Exhaustion is the one hard exclusion, and it is not a knob: a meter is spent at 100% used and
not one point earlier, because a subscription is bought to be used to the end.  The worker
pick (`pick_order`) ranks whatever is left by budget; the orchestrator choice (`ak orch`)
ignores both numbers and takes the default orchestrator while it still has something to spend.
"""

import fcntl
import itertools
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import command_help, config, terminal, usage_probe, worker
from .harness import load as harness_plugin

CACHE_TTL = 300
# A usage endpoint has a rate limit of its own, and everything here wants the same answer: the
# tick, every open menu, `ak usage`, every pick.  So the cadence belongs to the provider rather
# than to the caller -- nobody asks a provider's adapter again inside PROBE_EVERY, whoever they
# are and whatever for, a refused worker and a spent reset included, and a second caller past
# that age waits on the first one's lock instead of making a second request.  A minute is
# short enough that no row ever needs to say how old its reading is: an open menu asks that
# often, and the tick asks whenever it comes round.  Muse's usage call spends a model request,
# so its adapter answers from its own ten-minute cache in between (`muse_usage.CACHE_TTL`).
# A probe the endpoint refuses keeps the reading it could not replace, and that reading still
# ranks for PROBE_TRUSTED_FOR: a meter nobody could read again is not a meter nobody ever read,
# and calling one unknown is how a rate limit came to push every run onto the other providers.
PROBE_EVERY = 60
PROBE_TRUSTED_FOR = 6 * 3600
PROVIDER_METERS = "provider meters"
SESSION_SECS = 18000      # the 5h rolling window every harness reports as its session meter
FABLE_GAP_MARGIN = 2      # percentage points of slack before preferring Fable as executor

# --- the usage-limit reset --------------------------------------------------------------------
# A ChatGPT subscription earns "usage limit resets" that put the weekly window back to 0% and
# start a fresh week; the adapter whose manifest says `[usage] reset` counts what is left with
# `reset-status` and spends one with `reset`, and which adapter that is is its own toml's to say.
# Spending is worth it only once the week is nearly gone -- a reset applied at half a window
# throws the other half away -- and never more than one a day, so nothing that reads the meters
# in a loop can spend the lot.  Both numbers are the policy itself rather than a per-machine
# preference, so they are constants here and not config.toml keys.
RESET_AT_USED = 90        # weekly used% at or above which a reset is worth spending
RESET_EVERY_SECS = 86400  # and at most one applied reset in that many seconds
DRY_FOR = 3600            # how long a refusal that named no time, beside meters that name none
                          # either, parks its provider: long enough that nothing hands the same
                          # work straight back to it, short enough to cost at most an hour of a
                          # subscription that turns out to have had something left


def margin(cfg):
    """The one knob: points of pace slack.  It lets a payg provider in; it excludes nothing."""
    value = cfg.get("pace_margin", 10)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 100:
        raise config.Error("~/.agentkit/config.toml: pace_margin must be a number "
                           f"in [0, 100) (got {value!r})")
    return float(value)


def _elapsed(meter, now):
    resets_at, window = meter.get("resets_at"), meter.get("window_secs")
    for value in (resets_at, window):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return None
    return max(0.0, min(100.0, 100.0 * (window - (resets_at - now)) / window))


def _normalized(meter, now):
    """A reported meter as every reader of one expects it: with its elapsed% and its pace."""
    elapsed = _elapsed(meter, now)
    return {**meter, "elapsed": None if elapsed is None else round(elapsed, 1),
            "pace": None if elapsed is None else round(meter["used"] - elapsed, 1),
            "exhausted": False}


def _resets(harness):
    """Usage-limit resets this provider still holds, or None when its adapter cannot say.

    Only an adapter whose manifest says `[usage] reset` has any: the others answer 0 without
    being asked, because a count nobody can spend is not an unknown.  A reset is a whole meter
    of headroom, so it is read beside the meters and cached with them rather than at the moment
    something ranks.
    """
    if not harness_plugin(harness).usage["reset"]:
        return 0.0
    available = _number((_adapter_json(harness, "reset-status", 30) or {}).get("available"))
    return None if available is None else max(0.0, available)


def probe_refused(error):
    """The two words for a probe the endpoint would not answer, or None when it answered.

    `429` is the endpoint asking to be asked less often; a 5xx, or a probe that never came back,
    is it being briefly unreachable.  Neither says anything about the credentials the probe went
    out with, so neither may be read as a logout, and neither is a reason to throw away the
    reading it could not replace.  The menu row and `ak usage` both say these words off this one
    answer, so the two can never disagree about what happened.
    """
    text = str(error or "")
    if re.search(r"\b429\b|rate limit", text, re.I):
        return "rate limited"
    if re.search(r"\bHTTP 5[0-9][0-9]\b|timed out", text, re.I):
        return "unavailable"
    return None


def _probe(cfg, provider, now, account=None):
    try:
        harness, via = config.provider_harness(cfg, provider)
        adapter = config.adapter(harness)
    except config.Error as exc:
        return {"provider": provider, "meters": [], "error": f"unknown: {exc}",
                "pace": None, "resets": None, "exhausted": False, "probed_at": now}
    facts = harness_plugin(harness).usage
    said = None      # the adapter's own words for a call that ran; see the `auth` question below
    argv = [str(adapter), "usage"]
    if account is not None:
        # one account's meters: named to the adapter, whatever a turn this runs under was named
        argv = ["env", *(f"{k}={v}" for k, v in config.account_env(account).items()), *argv]
    try:
        if facts["capture"]:
            # a usage call that runs a model shares the caller's deadline, descendants included
            proc = usage_probe.capture(argv)
        else:
            proc = subprocess.run(argv, capture_output=True, timeout=30,
                                  encoding="utf-8", errors="replace")
        data = json.loads(proc.stdout)
        if not isinstance(data, dict):
            raise ValueError(f"expected a JSON object, got {type(data).__name__}")
        if proc.returncode != 0:
            data = {"meters": [], "error": f"unknown: {adapter.name} usage exited {proc.returncode}"}
        else:
            said = data.get("error")
        if not isinstance(data.get("meters", []), list):
            raise ValueError("expected a list of meters")
    except subprocess.TimeoutExpired:
        data = {"meters": [], "error": f"unknown: {adapter.name} usage timed out after 30s"}
    except (OSError, ValueError) as exc:
        data = {"meters": [], "error": f"unknown: {adapter.name} usage produced no JSON ({exc})"}
    # `probed_at` is when this adapter was asked, which is when an adapter that measures on
    # demand measured: the cadence below is counted from it.  A refusal is where the two part
    # company -- it has a fresh ask and no fresh measurement -- which is why `_kept` writes the
    # measurement down.
    out = {"provider": provider, "harness": harness, "via": via, "meters": [],
           "error": data.get("error"), "pace": None, "resets": _resets(harness),
           "exhausted": False, "probed_at": now}
    if facts["strips_timestamp"]:
        # an adapter that does not say when it measured leaves that to its own plugin: until
        # something recognises this response, it is not a response with an age
        out["fetched_at"] = None
        harness_plugin(harness).usage_extra(out, data, config.STATE)
    for meter in data.get("meters") or []:
        used = meter.get("used") if isinstance(meter, dict) else None
        if (not isinstance(meter, dict) or not isinstance(meter.get("name"), str)
                or _number(used) is None):
            out["error"] = out["error"] or (f"unknown: {adapter.name} reported a meter without "
                                            "a name and a numeric used%")
            continue
        out["meters"].append(_normalized(meter, now))
        pace = out["meters"][-1]["pace"]
        if pace is not None:
            out["pace"] = pace if out["pace"] is None else max(out["pace"], pace)
    if facts.get("none") and not out["error"] and not out["meters"]:
        # No meter is not a failed probe: a harness whose manifest says `[usage] none`
        # reads no budget at all, so the provider is neutral -- but only when the probe
        # itself ran and answered no meters.  A failed probe on any provider, metered or
        # not, stays unknown and ranks last, and a metered answer is a metered provider.
        out["none"] = True
        why = data.get("none")
        out["none_reason"] = why if isinstance(why, str) and why else "no meter"
    if not out["meters"] and not out["error"] and not out.get("none"):
        out["error"] = "unknown: adapter returned no meters"
    if said and not out["meters"] and probe_refused(said) is None:
        # The question only arises where there is nothing to show: a row with a meter on it never
        # says `no login` whatever went wrong beside the reading.
        # Only one party can say whether the credentials are the problem, and it is not the error
        # text: `token`, `401` and `login` turn up in lines a perfectly logged-in seat produces
        # too -- `HTTP 429 ...; token may be expired` is the one that read as a logout for an
        # hour.  So the harness's own `auth` verb is asked, and its `no` is the only thing that
        # ever puts `no login` on a row.  Only the adapter's own words are asked about: an
        # adapter that crashed, timed out or printed nothing usable was never reached at all, and
        # a probe the endpoint refused was asked with credentials it never complained about.
        out["logged_in"] = (worker.auth_ok(harness) if account is None
                            else worker.auth_ok(harness, account=account))[0]
    return out


def _cached_provider(provider, account=None):
    """What the snapshot holds for this provider -- or that account of it -- right now, or {}
    when it holds nothing.

    Read off the file rather than from a caller's copy, because the whole point is to see what
    another process wrote while this one was waiting for its lock.
    """
    try:
        blob = json.loads((config.STATE / "usage.json").read_text(encoding="utf-8"))
        prov = blob["providers"][provider]
        if account is not None:
            prov = prov["accounts"][account]
    except (OSError, ValueError, TypeError, KeyError):
        return {}
    return prov if isinstance(prov, dict) else {}


def _lock(provider, account=None):
    """The file one provider's probe -- or one account's of it -- is taken under, and dated by."""
    return config.STATE / (f"{provider}-probe.lock" if account is None
                           else f"{provider}.{account}-probe.lock")


def _cooling(provider, account=None):
    """Whether this provider's adapter was asked at all -- answered or not -- inside PROBE_EVERY.

    The moment is the one its lock file holds, written under that lock as the request goes out:
    not the snapshot's `probed_at`, which a caller that began its collection earlier can write
    back over a newer one, and which goes with the snapshot when that is deleted.  Each account
    of a provider is asked on its own minute: they are different logins.
    """
    try:
        asked = _number(float(_lock(provider, account).read_text()))
    except (OSError, ValueError):
        return False
    return asked is not None and 0 <= time.time() - asked < PROBE_EVERY


def _kept(cached, fresh, now):
    """`fresh` where the adapter answered, and the reading it could not replace where it did not.

    A refused probe leaves the meters, the moment they were really measured at, the resets counted
    beside them and their own error exactly as they stood, and records three things of its own:
    `probe_error` is what the endpoint said, `probe_failed_at` is when it said it, and
    `stale_since` is when this reading stopped being refreshed -- the first refusal after the last
    real answer, which is the age the picker measures its trust in the reading against.
    """
    if probe_refused(fresh.get("error")) is None:
        return fresh
    cached = cached if isinstance(cached, dict) else {}
    since = _number(cached.get("stale_since")) if cached.get("probe_error") else None
    kept = {key: cached[key] for key in ("meters", "fetched_at", "resets", "error", "notes")
            if key in cached}
    if "fetched_at" not in kept:
        # The ask that follows is this moment's; the measurement is not, so it is written down
        # here rather than inferred from it.  A cached record that recorded neither has an age
        # nobody can vouch for, which is not an age.
        kept["fetched_at"] = _number(cached.get("probed_at"))
    return {**fresh, **kept, "probe_error": fresh.get("error"), "probe_failed_at": now,
            "stale_since": now if since is None else since}


def _probe_gently(cfg, provider, account=None):
    """`_probe`, but at most once per PROBE_EVERY per provider across this whole host.

    Whoever asks -- the tick, an open menu, `ak usage`, a pick, a refused worker, a spent
    reset -- a reading younger than that is the answer, and only the first caller past it
    probes.  It writes the moment down in the provider's lock file, under that lock, before it
    asks, and every caller reads it under the same lock, so a second caller waits for the first
    one's answer instead of taking the reading from before it, or making a second request of an
    endpoint that has a rate limit of its own.  The clock is read there and not when the caller
    began: a caller reading several providers one after another asks each at its own moment.
    Every probe under that lock is bounded -- 30 seconds for an adapter that runs no model, Muse's own
    budget for the one that does -- so the wait for it is bounded as well, and a holder that
    dies gives the lock back with its file.

    The answer goes into the cache the moment it exists rather than when the caller has finished
    reading the other providers, because that is what the caller waiting on this lock comes back
    to read: an answer nobody can see yet is an answer nobody can be spared a request by.

    A provider that lists `accounts` is each of them read that way, every one with its own
    mark, under the provider: the provider's own fields are then the account a worker turn
    runs on next (`_gate_flags`).
    """
    names = config.accounts(cfg, provider) if account is None else []
    if names:
        now = time.time()
        old = _cached_provider(provider).get("accounts")
        old = old if isinstance(old, dict) else {}
        read = {name: _carry_mark(old.get(name), _without_past(
                    _probe_gently(cfg, provider, name), now, "the adapter"), now)
                for name in names}
        return _gate_flags({provider: {"provider": provider, "accounts": read}}, now, cfg)[provider]
    lock = _lock(provider, account)
    try:
        config.ensure_dirs()
        handle = lock.open("a")          # never "w": the file keeps when it was last asked
    except OSError:
        now = time.time()                # no lock to take: still one probe
        return _kept(_cached_provider(provider, account), _probe(cfg, provider, now, account), now)
    with handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        # Whoever we waited for has written their answer by now, and it is this one.
        cached = _cached_provider(provider, account)
        if _cooling(provider, account):
            return cached
        now = time.time()
        lock.write_text(repr(now))
        prov = _kept(cached, _probe(cfg, provider, now, account), now)
        # The mark travels with the record that replaces it, exactly as it does on the way out of
        # `collect`: a provider parked until it says it has capacity must not read as eligible in
        # the moment between this write and that one.  The caller still gets the bare reading, so
        # what the reset policy and a refusal's own re-read do with the mark is unchanged.
        _patch(provider, _carry_mark(cached, prov, now), now, account)
        return prov


def _adapter_json(harness, verb, timeout):
    """The one JSON object `<adapter> <verb>` printed, or None when it said nothing usable."""
    try:
        proc = subprocess.run([str(config.adapter(harness)), verb], capture_output=True,
                              timeout=timeout, encoding="utf-8", errors="replace")
        data = json.loads(proc.stdout)
    except (config.Error, subprocess.TimeoutExpired, OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _number(value):
    """`value` as a float when it really is a number, else None -- True is not a 1 here."""
    return (None if isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) else float(value))


def _write_reset_state(path, blob):
    config.ensure_dirs()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(blob))
    tmp.replace(path)


def _reset_applied_at(path):
    """When the last reset was spent, or None when none was, or the file cannot be read."""
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
        return _number(blob["applied_at"])
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _maybe_reset(cfg, provider, prov, now):
    """Spend one usage-limit reset on a nearly spent week, then read the meters back."""
    return _reset_policy(cfg, provider, prov, now, False)[0]


def _reset_policy(cfg, provider, prov, now, depleted):
    """The reset policy itself, as (the provider record now, was a credit really spent).

    The order is the whole safety of it.  The day is claimed on disk *before* the reset is
    asked for, so a spend nothing could record is never made and a crash between the two
    costs a day rather than a credit; the claim is dropped again when nothing was spent, so a
    refusal cannot block a reset the week actually needs.  The adapter says `reset` only for a
    credit that really went, and says it even when the re-read afterwards fails -- so the one
    answer that must never be lost is the one that is always recorded.

    `depleted` is a worker's own refusal, which is proof the window is spent whatever the
    meters read: it stands in for the 90% threshold and for nothing else.  A provider whose
    models were all removed spends nothing: a cached reading still names its harness, but no
    worker is left to use a credit.
    """
    try:
        config.provider_harness(cfg, provider)
    except config.Error:
        return prov, False
    harness = prov.get("harness")
    if not harness_plugin(harness).usage["reset"]:
        return prov, False
    weekly = _worst([m for m in prov.get("meters") or [] if m.get("window_secs") != SESSION_SECS])
    if not depleted and (weekly is None or weekly["used"] < RESET_AT_USED):
        return prov, False
    path = config.STATE / f"{provider}-reset.json"
    applied = _reset_applied_at(path)
    if applied is not None and 0 <= now - applied < RESET_EVERY_SECS:
        return prov, False
    available = _number(prov.get("resets"))   # counted by the probe that just read the meters
    if not available or available <= 0:
        return prov, False
    record = {"weekly_before": weekly["used"] if weekly else None, "depleted": depleted,
              "available_before": available}
    try:
        _write_reset_state(path, {**record, "applied_at": now, "outcome": "asked"})
    except OSError:
        return prov, False   # a spend that cannot be recorded is a spend that is not made
    result = _adapter_json(harness, "reset", 60) or {}
    spent = result.get("code") == "reset"
    left = _number(result.get("available"))
    try:
        _write_reset_state(path, {**record, "applied_at": now if spent else None,
                                  "attempted_at": now, "available_after": left,
                                  "weekly_after": _number(result.get("weekly_used")),
                                  "outcome": "reset" if spent else
                                             (result.get("error") or "no reset was applied")})
    except OSError:
        pass                 # the claim above still stands, so this costs a day and no credit
    if not spent:
        return prov, False
    # The re-read keeps the host's minute like any other.  Inside it the reading in hand is of
    # the window the credit just replaced, so it goes, as a rolled window does (`_reread`),
    # and a mark it carried is lifted (`_carry_mark`).  The week that replaced it is the one
    # the spend itself read back, when it could: `reset` asks the meters once the credit has
    # gone, so that is a fresh reading and no second request, and what a refused probe wrote
    # down about the old one (`_kept`) goes with it.  Without it the week waits for the next
    # probe.
    used, until = result.get("weekly_used"), result.get("resets_at")
    week = ([_normalized({**weekly, "used": used, "resets_at": until}, now)]
            if weekly and _number(used) is not None and _number(until) is not None else [])
    kept = {key: value for key, value in prov.items() if not week or key not in
            ("fetched_at", "probe_error", "probe_failed_at", "stale_since")}
    fresh = _without_past({**kept, "meters": week, "resets": None, "exhausted_until": None}
                          if _cooling(provider) else _probe_gently(cfg, provider),
                          now, "the adapter")
    left = max(0.0, available - 1 if left is None else left)
    # The re-read counts the resets again, and when it cannot -- the credits list is a second
    # request, free to fail on its own, and inside the minute there is no re-read -- the count
    # the spend itself came back with stands.
    # Losing it here would understate the headroom and outlook shown for the fresh week.
    if _number(fresh.get("resets")) is None:
        fresh["resets"] = left
    fresh["notes"] = [*(prov.get("notes") or []), f"usage-limit reset applied ({left:.0f} left)"]
    return fresh, True


def _past(meter, now):
    """True once this meter's window has rolled over, so its used% answers for nothing."""
    resets_at = meter.get("resets_at")
    return (isinstance(resets_at, (int, float)) and not isinstance(resets_at, bool)
            and resets_at <= now)


def _without_past(prov, now, name):
    """`prov` minus every meter whose window has rolled over, with its pace re-derived."""
    meters = [m for m in prov.get("meters") or [] if not _past(m, now)]
    paces = [m["pace"] for m in meters if m.get("pace") is not None]
    if prov.get("none") and not prov.get("error"):
        return {**prov, "meters": meters, "pace": max(paces, default=None)}
    return {**prov, "meters": meters, "pace": max(paces, default=None),
            "error": prov.get("error") or (None if meters else f"unknown: every meter {name} "
                                           "reports has already reset")}


def _reread(cfg, provider, cached, now):
    """A cached provider carrying a meter past its reset, read again.

    Probing is the real answer -- the adapter reports the window that replaced it, and for
    meta, the adapter refreshes its cached model probe after a quota window resets.
    But an adapter is free to hand back the window that just rolled over, and a
    provider config.toml no longer defines has no adapter left to ask at all, so the spent
    meters are dropped from whatever comes back: nothing past its reset survives the read.

    A rolled window is no reason to ask twice inside the host's probe cadence, so this waits for
    it like everything else: until then the spent meters are simply gone, and the row says the
    window reset rather than showing a percentage that answers for a week nobody has any more.
    """
    try:
        fresh = _without_past(_probe_gently(cfg, provider), now, "the adapter")
        return _carry_mark(cached, fresh, now)
    except config.Error:
        return _without_past(cached, now, "the cache")


def _gate_flags(providers, now, cfg):
    """Stamp `exhausted` at 100% used, retaining the orchestrator's reset-aware flag separately.

    The meters are cached for up to CACHE_TTL, so a flag computed when they were fetched could
    answer for a window that has since rolled over, or for an agentkit version that drew the
    line somewhere else.  Nothing decides on a cached verdict: it is re-derived on every read,
    and headroom and budget are re-derived here with it.
    """
    for name, prov in providers.items():
        listed = config.accounts(cfg, name)
        accounts = prov.get("accounts") if listed else None
        if isinstance(accounts, dict):
            # Several subscriptions: each is flagged on its own, and the provider is the one a
            # worker turn runs on next -- room before a spent one, then the most budget, then
            # the order the config lists them in -- so it is spent only when all of them are.
            accounts = _gate_flags({account: accounts[account] for account in listed
                                    if isinstance(accounts.get(account), dict)}, now, cfg)
            if accounts:
                best = min(accounts, key=lambda a: (accounts[a]["exhausted"],
                                                    accounts[a]["budget_reason"] is not None,
                                                    -accounts[a]["budget"]))
                prov.clear()
                prov.update(accounts[best], accounts=accounts, account=best)
        # A quota the harness recorded when it refused a run is the reading at once: it is a
        # file and no request, so neither the snapshot's five minutes nor the probe's minute
        # stands between it and a pick.  It is normalized as a probed meter is, because every
        # reader of the snapshot -- the table, the menu, the pick -- reads a probed one.
        recorded = harness_plugin(prov.get("harness")).usage_recorded(config.STATE, now)
        if recorded:
            prov.update(meters=[_normalized(meter, now) for meter in recorded], error=None)
        # a provider that refused a worker is parked until it said it would have
        # capacity, or until its meters show a window that opened after the mark
        until = _number(prov.get("exhausted_until"))
        marked_at = _number(prov.get("exhausted_at"))
        if until is None or until <= now:
            prov.pop("exhausted_until", None)
            prov.pop("exhausted_at", None)
            until = None
        elif marked_at is not None and _fresh_window(prov, marked_at, now):
            prov.pop("exhausted_until", None)
            prov.pop("exhausted_at", None)
            until = None
        prov["exhausted"] = until is not None
        for meter in prov.get("meters") or []:
            resets_at = meter.get("resets_at")
            pending = (isinstance(resets_at, (int, float)) and not isinstance(resets_at, bool)
                       and resets_at > now)
            # `resets_at` is the word the adapters and the cache use; `reset_at` is the one
            # `--json` promises its readers, so it is derived here with everything else and a
            # cache written before it existed carries it too -- `null` when nobody knows.
            meter["reset_at"] = _number(resets_at)
            meter["tier_a_exhausted"] = meter["used"] >= 100 and pending
            meter["exhausted"] = meter["used"] >= 100
            prov["exhausted"] = prov["exhausted"] or meter["exhausted"]
        split = _split_week(cfg, name, prov)
        # Derived on every read, including old caches and changes to config.toml.
        prov.pop("effective_used", None)
        prov.pop("gap", None)
        if split:
            prov["gap"] = split["gap"]
        meters = prov.get("meters") or []
        prov["pace"] = max((m["pace"] for m in meters if m.get("pace") is not None),
                           default=None)
        prov["headroom"] = provider_headroom(prov, cfg, name)
        budget, prov["budget_reason"] = provider_budget(prov, now)
        prov["budget"] = round(budget, 3)
        prov["budget_from_resets"] = round(budget_from_resets(prov, now), 3)
    return providers


_WRITES = itertools.count()   # a temporary name of each writer's own; see `_store`


def _store(cache, fetched_at, providers, reset_checked_at=None):
    """Replace the snapshot atomically, through a temporary file nobody else is writing.

    The tick, every menu's probe thread and every `ak usage` write this one file, and a probe
    now writes its own answer here the moment it has it, so two writers sharing one temporary
    name is how a rename comes to find it gone.  Each write takes a name of its own instead, and
    takes it away again, so a writer that dies mid-way leaves nothing behind either.
    """
    config.ensure_dirs()
    tmp = cache.with_suffix(f".tmp-{os.getpid()}-{next(_WRITES)}")
    try:
        tmp.write_text(json.dumps({"fetched_at": fetched_at, "providers": providers,
                                   "reset_checked_at": (fetched_at if reset_checked_at is None
                                                        else reset_checked_at)}))
        tmp.replace(cache)
    finally:
        tmp.unlink(missing_ok=True)


def _patch(provider, prov, now, account=None):
    """Put one freshly read provider -- or account of one -- into the cache, leaving the others
    and their age alone.

    fetched_at stays put for exactly the reason `collect` keeps it when it re-reads one
    provider: reading one must not stamp the others, which were not read, as newly measured.
    A snapshot that was not there is not one anybody assembled, so it starts stale, and the
    next read assembles the rest rather than answering with this one provider for five minutes.
    """
    cache = config.STATE / "usage.json"
    try:
        blob = json.loads(cache.read_text(encoding="utf-8"))
        providers = dict(blob["providers"])
    except (OSError, ValueError, TypeError, KeyError):
        blob, providers = {}, {}
    if account is not None:
        old = providers.get(provider) if isinstance(providers.get(provider), dict) else {}
        accounts = old.get("accounts") if isinstance(old.get("accounts"), dict) else {}
        prov = {**old, "accounts": {**accounts, account: prov}}
    providers[provider] = prov
    fetched, checked = _number(blob.get("fetched_at")), _number(blob.get("reset_checked_at"))
    try:
        _store(cache, 0.0 if fetched is None else fetched, providers,
               0.0 if checked is None else checked)
    except OSError:
        pass                 # a cache that cannot be written costs a re-probe, nothing more


def _fresh_window(prov, marked_at, now):
    """Whether a meter shows a window that opened after the mark with room left.

    A refusal parks the provider until the time it named, but the window it was refused
    for can start again first: the meter then reads a new window, begun after the mark
    was made, and that is the capacity the mark said was missing.  A meter that names
    no time, or none with room, is no such answer, and a spent replacement keeps the
    mark exactly as a spent week does.  The start has to have passed already: a length
    can be nominal -- a calendar-month plan reported on 30 days -- and a start still
    in the future is then the same window mismeasured, not a replacement.
    """
    if not isinstance(prov, dict):
        return False
    for meter in prov.get("meters") or []:
        if not isinstance(meter, dict):
            continue
        used = _number(meter.get("used"))
        if used is None or used >= 100:
            continue
        resets_at = _number(meter.get("resets_at"))
        window = _number(meter.get("window_secs"))
        if resets_at is None or window is None or window <= 0:
            continue
        if resets_at <= now:
            continue          # a window already rolled over answers for nothing
        start = resets_at - window
        if start > marked_at and start <= now:
            return True
    return False


def _carry_mark(old, prov, now):
    """A refusal's deadline outlives the meters it was recorded beside, until it has passed.

    A provider that has just refused a worker is parked until it says it has capacity again,
    and the meters it reports meanwhile are not that answer: the one that is, is the time the
    refusal itself named.  Once that time is behind us the mark is gone and the probe decides.
    A window that opened after the mark with room ends it sooner, and is that same answer.

    It is carried on the way *into* the reset policy and never on the way out, so a credit that
    opens a fresh week takes the mark with it: the meters a spend hands back are the capacity
    the mark said was missing, and re-applying it there would withhold what was just paid for.
    """
    until = _number((old or {}).get("exhausted_until"))
    if until is None or until <= now:
        return prov
    marked_at = _number((old or {}).get("exhausted_at"))
    if marked_at is not None and _fresh_window(prov, marked_at, now):
        return prov
    if marked_at is None:
        return {**prov, "exhausted_until": until}
    return {**prov, "exhausted_until": until, "exhausted_at": marked_at}


def collect(cfg, *, refresh=False):
    """Providers keyed by name, from a <=5 min cache.

    A meter can outlive its own window inside those five minutes, so whoever owns one is read
    again before anything is answered: the cache never reports a meter past its reset.  A cold
    read is held to the same rule -- an adapter is free to report a window that has already
    rolled over -- so nothing past its reset survives into the output or into the cache.

    Normal reads check the reset policy at most once per cache window, on a separate clock
    from snapshot freshness, so watch cannot starve a headless worker of an available reset.
    Watch's refresh bypasses this snapshot cache but never spends a reset. Muse's adapter
    still owns its longer probe cache: reading it does not force a paid request.

    A refresh is not a licence to probe, and neither is deleting state/usage.json:
    `_probe_gently` holds every caller to one request per provider per PROBE_EVERY, so what either
    really bypasses is this snapshot, not the adapters behind it. The snapshot's own
    `fetched_at` is when it was last assembled, which is what the five minutes above are
    counted from.
    """
    cache = config.STATE / "usage.json"
    now = time.time()
    try:
        blob = json.loads(cache.read_text(encoding="utf-8"))
        if not isinstance(blob, dict):
            blob = {}
    except (OSError, ValueError):
        blob = {}
    checked = _number(blob.get("reset_checked_at", blob.get("fetched_at")))
    due = checked is None or not 0 <= now - checked <= CACHE_TTL
    if not refresh:
        try:
            if now - blob.get("fetched_at", 0) <= CACHE_TTL and isinstance(blob["providers"], dict):
                # a provider the config no longer has is neither read again nor shown, however
                # fresh its cached reading
                providers = {name: prov for name, prov in blob["providers"].items()
                             if name in cfg["providers"]}
                # ... and so is one read before the config listed the accounts it lists now
                rolled = [name for name, prov in providers.items()
                          if any(_past(m, now) for m in prov.get("meters") or [])
                          or list(prov.get("accounts") or []) != config.accounts(cfg, name)]
                for name in rolled:
                    providers[name] = _reread(cfg, name, providers[name], now)
                missing = [name for name, prov in providers.items()
                           if _number(prov.get("resets")) is None]
                for name in missing:
                    try:
                        harness, _ = config.provider_harness(cfg, name)
                    except config.Error:
                        continue      # a provider whose models were all removed: nothing to ask
                    providers[name]["resets"] = _resets(harness)
                if due:
                    # the cached records already carry their own marks; a reset replaces the
                    # whole record, which is how a fresh week lifts one
                    providers = {name: _maybe_reset(cfg, name, prov, now)
                                 for name, prov in providers.items()}
                    checked = now
                if rolled or missing or due:
                    # fetched_at stays put: re-reading one provider must not extend the cache
                    # over the others, which were not re-read
                    _store(cache, blob["fetched_at"], providers, checked)
                return Readings(_gate_flags(providers, now, cfg))
        except (OSError, ValueError, TypeError, KeyError):
            pass
    providers = {}
    cached = blob.get("providers") if isinstance(blob.get("providers"), dict) else {}
    for name in cfg["providers"]:
        prov = _carry_mark(cached.get(name),
                           _without_past(_probe_gently(cfg, name), now, "the adapter"), now)
        providers[name] = _maybe_reset(cfg, name, prov, now) if not refresh and due else prov
    providers = _gate_flags(providers, now, cfg)
    _store(cache, now, providers, now if not refresh and due else (checked or 0))
    return Readings(providers)


class Readings(dict):
    """A usage read this module made, and beside it `harnesses`: why each harness cannot run.

    An attribute and not a key, so the providers stay exactly the providers for everything
    that compares, stores or prints them.  `collect` leaves it empty; a pick's `readiness`
    fills it.
    """
    harnesses = {}


def readiness(cfg, providers):
    """`providers`, with the harness of every model the config offers asked if it can run now.

    Asked on every pick and never kept with the meters: a login comes and goes between two
    probes, the credential a turn uses is not always the one the usage call used, one
    provider's models can sit on more than one harness, and a provider the snapshot does not
    carry yet is still one a pick can reach.  Only a read this module made is asked about: a
    stand-in for the usage layer was made by nothing on this machine, and is taken as it stands.
    """
    if not isinstance(providers, Readings):
        return providers
    read = Readings(providers)
    read.harnesses = {}
    for name in config.offered(cfg):
        harness = cfg["models"][name]["harness"]
        if harness not in read.harnesses:
            read.harnesses[harness] = harness_unready(harness)
    return read


def harness_unready(harness):
    """Why this harness cannot run a turn here, or None when nothing says it cannot.

    Not installed is its adapter missing, or its program nowhere to be found: the one its
    `[update] version` runs, else the adapter's own name, as `orch.agent_programs` reads them.
    Not logged in is its own `auth` verb saying no.  No answer withholds nothing.
    """
    try:
        config.adapter(harness)
    except config.Error:
        return f"{harness} is not installed"
    version = harness_plugin(harness).update["version"]
    named = isinstance(version, list) and version and isinstance(version[0], str) and version[0]
    if not config.harness_binary(version[0] if named else harness):
        return f"{harness} is not installed"
    return f"{harness} is not logged in" if worker.auth_ok(harness)[0] is False else None


def replenish(cfg, provider, depleted=True):
    """Read this provider's meters again, and spend a usage-limit reset if it holds one.

    The moment of need: a worker has just been refused, and that refusal is proof the window
    is spent whatever the cached used% said.  So the five-minute due clock and the 90%
    threshold are both out of the way here -- and nothing else is.  The day is still claimed
    on disk before the credit is asked for, still at most one reset in RESET_EVERY_SECS, the
    adapter is still asked at most once in PROBE_EVERY, and the reading goes into the cache so
    the next pick ranks on what the provider says now.  A seat stalled on its quota is not
    that proof (`watch.spend_reset`): `depleted=False` keeps the threshold.

    Returns (was a credit really spent, the resets left in hand).
    """
    now = time.time()
    prov = _without_past(_probe_gently(cfg, provider), now, "the adapter")
    prov, spent = _reset_policy(cfg, provider, prov, now, depleted)
    _patch(provider, prov, now)
    return spent, _number(prov.get("resets")) or 0.0


def _next_window(prov, now):
    """The soonest of this provider's windows still to roll over, or None when none does.

    Every window it reports, the 5h session one included: the session meter is a gate in its
    own right, so a provider refusing with a spent session and a half-empty week has capacity
    again in minutes, not at the end of the week.  Taking the soonest of them can let a
    provider back before it really has anything -- it is then refused once more and parked
    again -- and that is the side to be wrong on: withholding a subscription that has
    something left is the more expensive mistake.
    """
    ends = [_number(m.get("resets_at")) for m in prov.get("meters") or []]
    return min([end for end in ends if end is not None and end > now], default=None)


def mark_exhausted(cfg, provider, until=None, account=None):
    """Park a provider -- or that account of it -- that has just refused a worker, until it
    says it has capacity again.

    `until` is the harness's own "try again at", when its refusal named one; otherwise the
    soonest of the provider's own windows still to roll over, which is its other way of saying
    the same thing.  A refusal beside meters that name no time at all is still a refusal, so
    it parks the provider for `DRY_FOR` rather than for nothing: a provider left eligible
    after refusing is handed the same work again, and again.

    The mark lives in the usage cache beside the meters, so `pick_order` excludes this
    provider for every later pick in every run, and it is dropped the moment the deadline has
    passed, or a window that opened after the mark shows room.  An account's mark is its own:
    the provider stays eligible on its other accounts.  Returns the deadline recorded.
    """
    now = time.time()
    try:
        prov = collect(cfg).get(provider) or {}
    except config.Error:
        prov = {}
    if account is not None:
        prov = (prov.get("accounts") or {}).get(account) or {}
    if _number(until) is None or until <= now:
        until = _next_window(prov, now) or now + DRY_FOR
    _patch(provider, {**prov, "exhausted_until": float(until), "exhausted_at": float(now)},
           now, account)
    return float(until)


def account(cfg, provider):
    """(the account a worker turn on this provider runs on, whether it has room left).

    The one `_gate_flags` put first: with room before a spent one, then the most budget, then
    the order the config lists them in.  (None, None) for a provider that lists no accounts,
    which is asked nothing: it is one login, exactly as it always was.
    """
    names = config.accounts(cfg, provider)
    if not names:
        return None, None
    prov = collect(cfg).get(provider) or {}
    return (prov["account"] if prov.get("account") in names else names[0],
            not prov.get("exhausted"))


def _split_week(cfg, provider, prov):
    """The shared/scoped gap, only when config and both real meters describe a split."""
    entries = [e for e in cfg["models"].values() if e["provider"] == provider]
    claimed = {e["meter"] for e in entries if e.get("meter")}
    if len(claimed) != 1 or not any(not e.get("meter") for e in entries):
        return None
    scoped_name = next(iter(claimed))
    meters = {m["name"]: m for m in prov.get("meters") or []
              if m.get("window_secs") != SESSION_SECS}
    week, scoped = meters.get("weekly_all"), meters.get(scoped_name)
    if week is None or scoped is None or scoped_name == "weekly_all":
        return None
    gap = week["used"] - scoped["used"]
    return {"all_used": week["used"], "gap": gap, "scoped": scoped}


def _gating_meters(cfg, name, providers):
    """The meters that actually constrain this model.

    A model naming a `meter` is gated by that one and the shared weekly_all.  Otherwise use
    the provider's meters minus any meter another model claims: `weekly_scoped` is Fable's cap,
    so it must not gate Opus -- otherwise the orchestrator fallback from Fable to Opus could
    never fire.
    """
    entry = config.model(cfg, name)
    meters = providers.get(entry["provider"], {}).get("meters", [])
    want = entry.get("meter")
    if want:
        return [m for m in meters if m["name"] in (want, "weekly_all")], want
    claimed = {e["meter"] for n, e in cfg["models"].items()
               if n != name and e.get("meter") and e["provider"] == entry["provider"]}
    return [m for m in meters if m["name"] not in claimed], PROVIDER_METERS


def model_pace(cfg, name, providers):
    """(pace, label) for worker ranking; pace None when nothing is reported."""
    meters, label = _gating_meters(cfg, name, providers)
    paces = [m["pace"] for m in meters if m.get("pace") is not None]
    if not meters and label != PROVIDER_METERS:
        return None, f"{label} (not reported)"
    if not paces:
        return None, label
    worst = max(meters, key=lambda m: (m.get("pace") is not None, m.get("pace") or 0.0))
    detail = label if label == PROVIDER_METERS else f"{label} {worst['used']}%"
    return max(paces), detail


def _headroom(weekly, resets):
    """Meters left: what is unspent of this week, plus every reset still in hand.

    A reset puts the weekly window back to 0%, so one in hand is worth a whole meter and a
    week 60% gone with two of them (2.4) has three times what an untouched week alone has.
    None means nothing is reported, which is never the same as nothing being left.
    """
    if weekly is None or _number(weekly.get("used")) is None:
        return None
    return round(max(0.0, (100.0 - weekly["used"]) / 100.0) + (resets or 0.0), 3)


def _weekly(prov):
    """This provider's tightest weekly meter: the one furthest along, the 5h window aside.

    The session meter refills four or five times a day, so it says nothing about the week and
    is not what a week's capacity is counted from; it still gates on its own, at 100% used.
    """
    return _worst([m for m in prov.get("meters") or [] if m.get("window_secs") != SESSION_SECS])


def readable(prov, now):
    """This provider's weekly meters a number can actually be read from.

    A numeric used% in a window that has not rolled over, the 5h session aside: what a bar can
    be drawn from, and what the shared week is chosen among.
    """
    return [m for m in prov.get("meters") or []
            if m.get("window_secs") != SESSION_SECS and _number(m.get("used")) is not None
            and not _past(m, now)]


def shared_week(cfg, provider, prov, now=None):
    """The weekly meter every model of this provider draws on, or None when none can be read.

    A `meter` in config.toml is one model's own cap -- Fable's `weekly_scoped` -- so the week
    no model has claimed is the shared one, and that is the provider's number.  A scoped
    meter's percentage is never shown as the provider's: a menu reading `Claude 41% left` off
    Fable's cap while the account page says 52% is wrong on its face.  So when every week that
    can be read is somebody's private cap there is no shared week at all, and this says None
    rather than borrowing one of them: a row that cannot be drawn is better than a wrong one.
    The picker is unaffected -- it ranks on the tightest meter, whoever owns it.

    The menu's row and the `resets` column of the table both read this one answer, so the two
    can never disagree about which week they are naming the reset time of.
    """
    meters = readable(prov, time.time() if now is None else now)
    claimed = {entry["meter"] for entry in cfg["models"].values()
               if entry.get("provider") == provider and entry.get("meter")}
    return _worst([m for m in meters if m.get("name") not in claimed])


def provider_headroom(prov, cfg, provider=None):
    """Worker headroom, from the tightest real weekly meter and the provider's resets.

    Read from the meters rather than from `prov["headroom"]`, which a cache written by another
    version of agentkit -- or by hand -- is free not to carry.  A reset count the adapter could
    not give counts as none: capacity nobody has confirmed is not capacity to display.
    """
    return _headroom(_weekly(prov), _number(prov.get("resets")) or 0.0)


def model_headroom(cfg, name, providers):
    """This worker's headroom, or None when nothing is reported.

    Count the model's own real weekly meters. Resets belong to the provider.
    """
    meters, _ = _gating_meters(cfg, name, providers)
    provider = config.model(cfg, name)["provider"]
    resets = _number(providers.get(provider, {}).get("resets")) or 0.0
    return _headroom(_worst([m for m in meters if m.get("window_secs") != SESSION_SECS]), resets)


def _stale(prov, now):
    """Whether a reading no probe has been able to refresh has stopped answering for anything.

    A refused probe keeps the last reading and the picker ranks on it, because a week's meter
    does not move fast and a provider whose meter was rate limited has not stopped holding a
    subscription: ranking it unknown-last is exactly how a rate limit came to push every run onto
    the other providers.  Once the refusals have run on for PROBE_TRUSTED_FOR nobody can say what
    it has left any more, and unknown-last is then the honest answer rather than the expensive one.
    """
    prov = prov if isinstance(prov, dict) else {}
    since = _number(prov.get("stale_since"))
    return bool(prov.get("probe_error")) and (since is None
                                              or not 0 <= now - since <= PROBE_TRUSTED_FOR)


def _budget(prov, weekly, now=None):
    """(budget, unknown reason), using current window time rather than cached elapsed%.

    Every usage-limit reset in hand is one whole weekly allowance on top of what is left of
    this week -- a count, never a percentage and never scaled by the window -- so a provider
    holding a spare week is spent before the others.  A count its adapter could not give adds
    nothing and leaves the budget known: unconfirmed capacity is not an unknown reading.
    """
    now = time.time() if now is None else now
    if prov.get("error"):
        return 0.0, str(prov["error"])
    if _stale(prov, now):
        return 0.0, str(prov["probe_error"])
    if weekly is None or _number(weekly.get("used")) is None:
        return 0.0, "no weekly meter reported"
    resets_at, window = (_number(weekly.get(k)) for k in ("resets_at", "window_secs"))
    if resets_at is None or window is None or resets_at <= 0 or window <= 0:
        return 0.0, "gate meter has no valid reset time or window length"
    left = max(0.0, min(1.0, (100.0 - weekly["used"]) / 100.0))
    remaining = max(0.0, min(1.0, (resets_at - now) / window))
    if remaining == 0:
        return 0.0, "gate window has reset; awaiting fresh meters"
    return (left + (_number(prov.get("resets")) or 0.0)) / remaining, None


def provider_budget(prov, now=None):
    """The smallest non-session budget; every gate must support the spending rate."""
    now = time.time() if now is None else now
    if prov.get("none") and not prov.get("error"):
        return 1.0, None   # meterless but answering: neutral, ranked by the normal rules
    budgets = [_budget(prov, meter, now) for meter in prov.get("meters") or []
               if meter.get("window_secs") != SESSION_SECS]
    return min(budgets, key=lambda value: (value[1] is None, value[0]),
               default=_budget(prov, None, now))


def budget_from_resets(prov, now=None):
    """How much of the ranking budget the resets in hand supply, 0.0 when they supply none.

    The subtraction the usage table shows: what this provider ranks on now, less what it would
    rank on with an empty hand.  A budget nobody could read is zero either way.
    """
    now = time.time() if now is None else now
    budget, reason = provider_budget(prov, now)
    if reason is not None or not _number(prov.get("resets")):
        return 0.0
    return budget - provider_budget({**prov, "resets": 0.0}, now)[0]


def model_budget(cfg, name, providers, now=None):
    """(budget, unknown reason) from this worker's tightest budget, its provider's resets in it."""
    meters, _ = _gating_meters(cfg, name, providers)
    prov = providers.get(config.model(cfg, name)["provider"], {})
    return provider_budget({**prov, "meters": meters}, now)


def model_exhausted(cfg, name, providers):
    """(exhausted, why) for the meters gating this model: one of them reads 100% used.

    Or its provider refused a worker outright, which is the same answer from the only party
    that really knows: a meter below 100 is not permission to be refused again.

    Tier B requires a later probe before spending a full meter again, even without a reset
    timestamp. Tier A retains its existing cached flags in `model_spent`.
    """
    meters, _ = _gating_meters(cfg, name, providers)
    provider = config.model(cfg, name)["provider"]
    prov = providers.get(provider, {})
    until = _number(prov.get("exhausted_until") if isinstance(prov, dict) else None)
    now = time.time()
    if until is not None and until > now:
        marked_at = _number(prov.get("exhausted_at"))
        if marked_at is None or not _fresh_window(prov, marked_at, now):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(until))
            return True, f"{provider} ran dry; nothing is picked on it until {when}"
    spent = [m for m in meters if m["used"] >= 100]
    if not spent:
        return False, None
    worst = max(spent, key=lambda m: m["used"])
    return True, f"{worst['name']} {worst['used']}% used >= 100"


def _watched(cfg, name, providers):
    """The meters gating the model plus its provider's 5h session meter, and their label."""
    entry = config.model(cfg, name)
    meters, label = _gating_meters(cfg, name, providers)
    named = {m["name"] for m in meters}
    return meters + [m for m in providers.get(entry["provider"], {}).get("meters") or []
                     if m.get("window_secs") == SESSION_SECS and m["name"] not in named], label


def spent_meter(cfg, name, providers):
    """The worst meter this model watches that reads 100% used, or None: what the new-session
    screen calls spent.  Unlike `model_spent`, a meter whose reset nobody knows counts too --
    the screen only declines to choose the model for him, and says when it resets if it can."""
    spent = [m for m in _watched(cfg, name, providers)[0] if m.get("used", 0) >= 100]
    return max(spent, key=lambda m: m["used"]) if spent else None


def unready(cfg, name, providers):
    """Why this model's harness cannot run a turn here, or None when nothing says so.

    Read off the `harnesses` a pick's `readiness` asked; a read that carries none withholds
    nothing, as a turn goes ahead on an `auth` verb that said nothing.
    """
    return getattr(providers, "harnesses", {}).get(config.model(cfg, name)["harness"])


def model_spent(cfg, name, providers):
    """(spent, why) for the orchestrator choice: this model has nothing left to spend at all.

    The meters gating the model plus its provider's 5h session meter, which a model naming a
    weekly `meter =` runs inside without its own gate ever seeing it.  The used side only --
    that choice does not read pace, because being ahead of pace is not a reason to refuse the seat
    the user works from.
    """
    watched, label = _watched(cfg, name, providers)
    spent = [m for m in watched if m.get("tier_a_exhausted", m.get("exhausted"))]
    if spent:
        worst = max(spent, key=lambda m: m["used"])
        return True, f"{worst['name']} {worst['used']}% used >= 100"
    if not watched:
        return False, f"{label} (not reported)"
    worst = max(watched, key=lambda m: m["used"])
    return False, f"{worst['name']} {worst['used']}% used < 100"


def _fable_pair_available(cfg, providers, order):
    """Fable can execute and a legal reviewer in this order has reported headroom."""
    from . import run
    if "fable" not in order or model_spent(cfg, "fable", providers)[0]:
        return False
    if (model_budget(cfg, "fable", providers)[1] is not None
            and any(model_budget(cfg, n, providers)[1] is None for n in order)):
        return False
    return any((model_headroom(cfg, n, providers) or 0) > 0
               for n in run.reviewer_order(cfg, "fable", order))


def pick_order(cfg, providers, workers=None, *, role="executor", orchestrator=None, quiet=False,
               repo=None, skip=()):
    """The workers, highest budget first, with a Fable executor preference when it lags.

    Budget divides the fraction unspent, plus one whole allowance for each usage-limit reset in
    hand, by the fraction of its window still to go. Unknown readings have budget zero and sort
    after every known model; equal budgets keep list order. The one exclusion is a gate meter
    at 100% used; `skip` names models a caller leaves out before any of this reads the list.
    payg providers are the exception: they cost money,
    so they stay out while any subscription model is still below pace, and a subscription model
    whose meters report nothing counts as below it.  Where the harness's own config says what
    a model is paid from, that outranks the provider's `mode`.

    A worker selection is absolute; lag can only prefer a model already in it.
    Reviewers keep the normal ranking and worker selection. A launch banner supplies the new
    orchestrator explicitly, since the caller may still be in another seat. JSON output uses
    `quiet` because the providers already carry their unknown reasons as structured fields.
    """
    tier_b = list(workers) if workers is not None else config.workers(cfg)
    if orchestrator is None:
        session = config.active_session(cfg)
        orchestrator = session.get("orchestrator") if session else None
    fable = cfg["models"].get("fable", {})
    provider = fable.get("provider")
    split = _split_week(cfg, provider, providers.get(provider, {}))
    behind = (role == "executor" and split is not None
              and split["scoped"]["name"] == fable.get("meter")
              and split["gap"] > FABLE_GAP_MARGIN)
    added = False
    if behind and "fable" not in tier_b and "fable" in config.offered(cfg):
        if workers is None and orchestrator is None:
            tier_b = [*tier_b, "fable"]
            added = True
    tier_b = [n for n in tier_b if n not in skip]
    limit = margin(cfg)

    def mode(name):
        entry = config.model(cfg, name)
        return (harness_plugin(entry["harness"]).mode(entry)
                or cfg["providers"][entry["provider"]].get("mode", "subscription"))

    def pace(name):
        return model_pace(cfg, name, providers)[0]

    gates = {n: model_exhausted(cfg, n, providers) for n in tier_b}
    if not quiet:
        for name, (exhausted, reason) in gates.items():
            if exhausted:
                print(f"pick {role}: {name} excluded: {reason}", file=sys.stderr)
    candidates = [n for n in tier_b if not gates[n][0]]
    subs = [n for n in candidates if mode(n) != "payg"]
    if any(pace(n) is None or pace(n) <= limit for n in subs):
        candidates = subs
    now = time.time()
    budgets = {n: model_budget(cfg, n, providers, now) for n in candidates}
    for name, (budget, reason) in budgets.items():
        if reason is not None and not quiet:
            provider = config.model(cfg, name)["provider"]
            reason = reason.removeprefix("unknown: ")
            print(f"pick {role}: {name} ({provider}) budget {budget:g} unknown: {reason}; "
                  "ranked last", file=sys.stderr)
    order = sorted(candidates, key=lambda n: (budgets[n][1] is not None, -budgets[n][0]))
    # A close budget is deliberately the only place history can influence selection.  Keep
    # models without five finished samples at their budget positions; the historical models
    # occupying those positions are then ordered by success, with speed as the tie-break.
    try:
        from . import history
        best = max((budgets[name][0] for name in order), default=None)
        if best is not None:
            close = [name for name in order if budgets[name][1] is None
                     and best - budgets[name][0] <= .15]
            stats = ({name: history.role_stats(repo, role, name) for name in close}
                     if repo is not None else {name: None for name in close})
            eligible = [name for name in close if stats[name] and stats[name][1] >= 5]
            positions = [index for index, name in enumerate(order) if name in eligible]
            ranked = sorted(eligible, key=lambda name: (
                -stats[name][0], stats[name][2] if stats[name][2] is not None else float("inf"),
                order.index(name)))
            for index, name in zip(positions, ranked):
                order[index] = name
    except (AttributeError, OSError, TypeError, ValueError, KeyError):
        pass
    if behind and _fable_pair_available(cfg, providers, order):
        return ["fable", *(n for n in order if n != "fable")]
    if added:
        # Adding a subscription worker can change payg eligibility; restore the normal pick too.
        return pick_order(cfg, providers, [n for n in tier_b if n != "fable"], role="reviewer",
                          quiet=quiet, repo=repo)
    return order


# `resets` is when the shared week opens again, the same answer the menu row gives after that
# same word, off the same meter.  The usage-limit credits that used to hold that heading are
# `resets held`, which is what every note about them already says in longer words.  `left`
# names no week, because not every window is one: MiMo's plan runs thirty days.
HEADERS = ("provider", "model(s)", "left", "resets", "week elapsed", "session",
           "resets held", "headroom", "budget", "outlook")


def _pct(value):
    return "-" if value is None else f"{value:.0f}%"


def _left(used):
    """What a meter at `used`% has left, in the menu's polarity, or None when it reports nothing."""
    used = _number(used)
    return None if used is None else max(0.0, min(100.0, 100.0 - used))


def _num(value, places):
    return "-" if value is None else f"{value:.{places}f}"


def _budget_label(value, reason):
    if reason is not None:
        return "unknown"
    value = round(value, 1)
    return f"{value:.1f} " + ("slack" if value > 1 else "ahead" if value < 1 else "in step")


def _worst(meters):
    """The meter of this set that is furthest along, or None when there is no set."""
    return max(meters, key=lambda m: m["used"], default=None)


def reset_when(meter, now=None):
    """When this meter's window opens again, in the reader's own time: `Fri 14:00`, or `in 3d`.

    More than six days out, in a window longer than a week, it is a date, `23 Oct`: a weekday
    that far off reads as this week's, and a 30-day plan's reset is not.  A weekly window keeps
    its weekday, since it can never be further off than that.  A meter that names no moment
    but says how long it still has to run -- `resets_in` seconds -- gives the duration instead,
    because that is still an answer.  One that says neither says nothing: a guessed reset is
    the one number here nobody could check.  The menu prints this after the word `resets` and
    the table under that heading, so both say the same thing.
    """
    now = time.time() if now is None else now
    meter = meter if isinstance(meter, dict) else {}
    at = _number(meter.get("resets_at"))
    if at is not None and at > now:
        try:
            when = time.localtime(at)
            window = _number(meter.get("window_secs"))
            if at - now > 6 * 86400 and not (window and window <= 7 * 86400):
                return f"{when.tm_mday} {time.strftime('%b', when)}"
            return time.strftime("%a %H:%M", when)
        except (OverflowError, OSError, ValueError):
            return ""
    secs = _number(meter.get("resets_in"))
    return f"in {terminal.format_age(secs)}" if secs and secs > 0 else ""


def _rate(meter):
    """Used% per hour, as this window has actually been spent, or None when it cannot be seen.

    A window nothing has been spent in yet -- no elapsed time, or none reported -- has no rate
    to project from, and a made-up one would be the one number here nobody could check.
    """
    elapsed, window = _number(meter.get("elapsed")), _number(meter.get("window_secs"))
    if elapsed is None or window is None or elapsed <= 0 or window <= 0:
        return None
    return meter["used"] / (elapsed / 100.0 * window / 3600.0)


def outlook(prov):
    """When this provider runs dry, at the rate it has been spent since its window opened.

    The observed drain rate is the only thing there is to go on, and headroom is what it has
    left to eat, the resets in hand included.  When that outlasts the window there is nothing
    to warn about -- the meter refills before the rate empties it -- and that is `on track`.  A
    provider that reports no week, or no time to have spent one in, says so rather than being
    guessed at, and a spent one says that outright.
    """
    if prov.get("exhausted"):
        return "exhausted"
    week = _weekly(prov)
    room = _headroom(week, _number(prov.get("resets")) or 0.0)
    if prov.get("error") or room is None:
        return "unknown"
    rate = _rate(week)
    if rate is None:
        return "-"
    if rate <= 0:
        return "on track"           # nothing spent yet: this week ends before the rate bites
    hours = room * 100.0 / rate
    window_left = (100.0 - week["elapsed"]) / 100.0 * week["window_secs"] / 3600.0
    return "on track" if hours >= window_left else f"runs out in ~{max(1, round(hours / 24))}d"


def _accounts(providers):
    """(label, provider, record) per provider, and per account of one that lists several."""
    for name, prov in providers.items():
        accounts = prov.get("accounts")
        if isinstance(accounts, dict) and accounts:
            yield from ((f"{name}:{account}", name, record) for account, record in accounts.items())
        else:
            yield name, name, prov


def rows(cfg, providers):
    """One row per provider, in plain words: what is left of its week and session, and how long.

    `left` is the tightest weekly meter, because that is what the picker ranks on;
    `resets` is the shared week's, because that is the week the menu row names and the two
    must say the same thing.  On a split allowance they can be different meters, which is why
    the two lines under the table print both.  A provider with several accounts is a row per
    account, `anthropic:second`, each on its own meters.
    """
    now = time.time()
    out = []
    for label, name, prov in _accounts(providers):
        week = _weekly(prov)
        session = _worst([m for m in prov.get("meters") or []
                          if m.get("window_secs") == SESSION_SECS])
        models = ", ".join(n for n, e in cfg["models"].items() if e.get("provider") == name)
        out.append((label, models or "-", _pct(_left(week["used"] if week else None)),
                    reset_when(shared_week(cfg, name, prov, now), now) or "-",
                    _pct(week["elapsed"] if week else None),
                    _pct(_left(session["used"] if session else None)),
                    _num(_number(prov.get("resets")), 0),
                    _num(provider_headroom(prov, cfg, name), 1),
                    _budget_label(*provider_budget(prov, now)), outlook(prov)))
    return out


def review_pair(cfg, providers):
    """The first runnable pair, using the loop's eligibility and company preference."""
    from . import run
    try:
        executor, reviewer = run.pick_models(cfg, providers, None, None, lambda _: None,
                                             quiet=True)
    except run.QuotaDry:
        return None
    return {"executor": executor, "reviewer": reviewer,
            "same_provider": config.model(cfg, executor)["provider"] ==
                             config.model(cfg, reviewer)["provider"]}


def render(cfg, providers, order, *, repo=None):
    now = time.time()
    table = [HEADERS] + rows(cfg, providers)
    widths = [max(len(row[i]) for row in table) for i in range(len(HEADERS))]
    width = terminal.width()
    if width >= 60 and sum(widths) + len(widths) - 1 > width:
        table[0] = ("provider", "model(s)", "left", "resets", "elapsed", "session",
                    "held", "room", "budget", "outlook")
        widths = [max(terminal.cells(row[i]) for row in table) for i in range(len(HEADERS))]
        # an account's row keeps its whole name: `anthropic:s…` would not say which one it is
        named = max((terminal.cells(label) for label, name, _ in _accounts(providers)
                     if label != name), default=0)
        for i, cap in ((1, 14), (0, max(12, named)), (9, 18)):   # model(s), provider, outlook
            widths[i] = min(widths[i], cap)
    if sum(widths) + len(widths) - 1 <= width:
        lines = [" ".join(terminal.pad(cell, w) for cell, w in zip(row, widths)).rstrip()
                 for row in table]
        lines[0] = terminal.styled(lines[0], "dim")
    else:
        # The full headings and all the meters still fit on a phone, as aligned label/value
        # pairs under each provider. Nothing numeric is silently dropped to squeeze a row.
        lines = []
        label_width = max(len(label) for label in HEADERS[2:])
        for row in table[1:]:
            if lines:
                lines.append("")
            lines.extend(terminal.styled(line, "bold")
                         for line in terminal.wrap(f"{row[0]} · {row[1]}", width))
            for label, value in zip(HEADERS[2:], row[2:]):
                prefix = "  " + label.ljust(label_width) + "  "
                for n, part in enumerate(terminal.wrap(value, width - len(prefix))):
                    lines.append((prefix if n == 0 else " " * len(prefix)) + part)
    for name, prov in providers.items():
        split = _split_week(cfg, name, prov)
        if split is None:
            continue
        scoped, gap = split["scoped"], split["gap"]
        models = [(n, e) for n, e in cfg["models"].items() if e["provider"] == name]
        owners = ", ".join(n for n, e in models if e.get("meter") == scoped["name"])
        workers = ", ".join(n.capitalize() for n, e in models if not e.get("meter"))
        preference = ("preferring Fable as executor" if order[:1] == ["fable"]
                      and _fable_pair_available(cfg, providers, order) else "normal selection")
        verdict = (f"{owners} behind by {gap:g}: {preference}"
                   if gap > FABLE_GAP_MARGIN else f"{owners} ahead by {-gap:g}: {workers} preferred"
                   if gap < -FABLE_GAP_MARGIN else "in step")
        if gap > FABLE_GAP_MARGIN and split["all_used"] >= 100:
            verdict = f"{owners} behind by {gap:g}: weekly_all exhausted"
        # the same polarity as the column; the gap stays in points of the week spent
        lines += [f"{name}: weekly_all {_pct(_left(split['all_used']))} left, "
                  f"{scoped['name']} {_pct(_left(scoped['used']))} left, gap {gap:g}",
                  f"  {verdict}"]
        budgets = [(n, model_budget(cfg, n, providers, now)) for n, _ in models]
        if len({value for _, value in budgets}) > 1:
            lines.append("  budget: " + "; ".join(f"{n} {_budget_label(*value)}"
                                                  for n, value in budgets))
    # a reset in hand is a whole week of the budget that ranks: say what it is worth, and what
    # the provider would rank on without it -- a credit it really holds is named even when no
    # budget can be read, because the count is confirmed whatever the meters did
    for name, prov in providers.items():
        count = _number(prov.get("resets")) or 0.0
        if count <= 0:
            continue
        one = count == 1
        budget, reason = provider_budget(prov, now)
        detail = (f"budget {_num(budget - budget_from_resets(prov, now), 1)} "
                  f"without {'it' if one else 'them'}" if reason is None else
                  "budget unknown: " + reason.removeprefix("unknown: "))
        lines.append(f"{name}: {count:g} reset{'' if one else 's'} in hand counted as "
                     f"{'one full week' if one else f'{count:g} full weeks'} ({detail})")
    # the numbers say the provider is unknown; only the adapter can say why
    lines += [f"note: {name} {prov['error']}" for name, _, prov in _accounts(providers)
              if prov.get("error")]
    # ... and a probe the endpoint would not answer says so in the menu's own two words, and
    # what the endpoint said; the reading it could not replace stands in the row as it was
    for name, _, prov in _accounts(providers):
        note = probe_refused(prov.get("probe_error"))
        if note is None:
            continue
        lines.append(f"note: {name} {note}: " + str(prov["probe_error"]).removeprefix("unknown: "))
    # a reset the policy spent, for as long as the meters it went and re-read stay cached
    lines += [f"{name}: {note}" for name, prov in providers.items()
              for note in prov.get("notes") or []]
    try:
        from . import history
        if repo is not None:
            for model in order:
                for role in ("executor", "reviewer"):
                    line = history.usage_line(repo, model, role)
                    if line:
                        lines.append(terminal.styled(line, "dim"))
    except (OSError, TypeError, ValueError):
        pass
    lines.append("pick order: " + (", ".join(order) if order else "(none: every worker's provider is exhausted)"))
    pair = review_pair(cfg, providers)
    if pair:
        lines.append(f"review: {pair['executor']} by {pair['reviewer']}")
        if pair["same_provider"]:
            lines.append("one provider: reviewer on the same company")
    return "\n".join(part for line in lines for part in
                     ([line] if terminal.cells(terminal.plain(line)) <= width else
                      terminal.wrap(line, width)))


def main(argv):
    if command_help.show("usage", argv):
        return 0
    as_json = "--json" in argv
    for arg in argv:
        if arg != "--json":
            raise config.Error(f"usage: ak usage [--json]  (got {arg!r})")
    cfg = config.load()
    providers = collect(cfg)
    repo = Path.cwd().name
    order = pick_order(cfg, providers, quiet=as_json, repo=repo)
    if as_json:
        json.dump({"providers": providers, "pick_order": order,
                   "review": review_pair(cfg, providers)}, sys.stdout, indent=2)
        print()
    else:
        print(render(cfg, providers, order, repo=repo))
    return 0
