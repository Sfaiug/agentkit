"""Owner, 28 Oct 2026: ak's checks never hold a login that can renew, and need no login of their
own, so no user signs in twice.

On 28 Oct a check renewed the host's login in the throwaway HOME it was linked into, retiring
the pair every seat held.  So each harness whose manifest lists `[worker] logins` lends a check's
HOME a copy nothing can renew, its adapter's `lend`, of its usual login whatever AGENTKIT_ACCOUNT
names, and nothing goes back; one with none to lend, or no adapter here, lends none.

A subscription added on `c` signs in under an account of its own (#1759), so a harness's usual
login may not exist.  Asked for subscriptions, one with none to lend lends instead the first of
the caller's config's subscriptions, on a provider it runs, that has one, where a turn naming
that account reads it, and says which, for the caller to list in its HOME's config.  Only when
asked: a HOME whose config lists none would hold a copy no turn reads.

Usage: python3 -m agentkit.lend [--subscriptions] <home>
    a line per harness lent, its name and the files it placed, by their path in <home>, and with
    --subscriptions a last line, the JSON {provider: account} of each lent by name; exit 1
    saying why where a lend failed or a place it takes in <home> is taken.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import config

FAILED = (config.Error, OSError, ValueError, subprocess.TimeoutExpired)    # what `into` raises


def _lenders():
    return [harness for harness, data in dict(config.manifests()).items()
            if data.get("worker", {}).get("logins") and config.adapter_path(harness).exists()]


def into(home, subscriptions=False):
    """Lend `home` each harness's login: ({harness: [files placed]}, the epoch second the first
    of them stops authenticating and its harness, None where none does), and with
    `subscriptions` a third value, {provider: account} of each subscription lent by name.  Where a
    lend fails or a place it takes is taken it raises, leaving none lent: no caller is told what
    to keep out of what it saves."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    listed = _listed() if subscriptions else {}
    lent, ends, named = {}, [], {}
    try:
        for harness in _lenders():
            for provider, account in [(None, None), *listed.get(harness, ())]:
                env = {**os.environ, **config.account_env(account),
                       **config.provider_env([provider] if provider else ())}
                # Lent into a folder of its own, so what it placed is known without its
                # harness's layout, and linked from there into `home`, which refuses a place taken.
                with tempfile.TemporaryDirectory(prefix=".lend-", dir=home) as staging:
                    proc = subprocess.run([str(config.adapter(harness)), "lend", staging,
                                           *(["own"] if account else [])], env=env, text=True,
                                          stdin=subprocess.DEVNULL, capture_output=True,
                                          timeout=60)   # asking for saved keys boots a server
                    if proc.returncode == 1:
                        continue
                    if proc.returncode:
                        raise config.Error(f"{harness} lend exited {proc.returncode}: "
                                           f"{proc.stderr.strip()}")
                    lent[harness] = []
                    for path in sorted(Path(staging).rglob("*")):
                        if path.is_file():
                            place = home / path.relative_to(staging)
                            place.parent.mkdir(parents=True, exist_ok=True)
                            os.link(path, place)
                            lent[harness].append(place)
                    if proc.stdout.strip():
                        ends.append((int(proc.stdout), harness))
                if account:
                    named[provider] = account
                break
    except BaseException:
        for place in (place for files in lent.values() for place in files):
            place.unlink()
        raise
    return (lent, min(ends, default=None), *([named] if subscriptions else []))


def _listed():
    """{harness: [(provider, account)]}: each subscription the caller's config lists by name, in
    its order, under each harness its provider runs on -- `provider_harnesses`, so one whose
    models were all removed still counts.  The default account is the usual login, and a config
    that cannot be read lists none."""
    try:
        cfg = config.load()
    except config.Error:
        return {}
    listed = {}
    for provider in cfg["providers"]:
        for harness in config.provider_harnesses(cfg, provider):
            listed.setdefault(harness, []).extend(
                (provider, account) for account in config.accounts(cfg, provider)
                if account != config.DEFAULT_ACCOUNT)
    return listed


def first_lapse():
    """`into`'s first lapse for a check started now; None where a lend fails, which that check
    reports.  Each harness's `auth seat` runs first, in this HOME: where an adapter renews a lapsed
    login in place, it is lent fresh.  So only the tick asks this: a gate's own lending, `into`
    alone, must not renew a real login from the landing suite."""
    from . import worker    # here, not at the top: a check's own lend would load all of ak
    try:
        for harness in _lenders():
            worker.auth_ok(harness, seat=True)
        with tempfile.TemporaryDirectory(prefix="lend-", dir=config.TMP) as home:
            return into(home)[1]
    except FAILED:
        return None


if __name__ == "__main__":
    subscriptions = sys.argv[1] == "--subscriptions"
    home = Path(sys.argv[1 + subscriptions])
    try:
        lent, _, *named = into(home, subscriptions)
    except FAILED as exc:
        sys.exit(f"lend: {exc}")
    for harness, files in lent.items():
        print(harness, *(path.relative_to(home) for path in files))
    for accounts in named:
        print(json.dumps(accounts))
