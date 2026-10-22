"""A harness's `login-end` answered per account, and a tick of an answer-key Home that stays
on loopback.

`Logins(home)` puts `<harness>.sh` in a directory the Home's AGENTKIT_ADAPTER_DIR names, in
place of that harness's adapter.  Its `login-end` prints what `answer` set for the account
AGENTKIT_ACCOUNT names (`default` where it names none) and fails for an account given no
answer; every other verb fails, as an adapter with nothing to say.  `asked()` is the
AGENTKIT_ACCOUNT of each `login-end` call so far, oldest first, "" where it named none.

`tick(home)` runs one `ak watch`.  A tick also reads the public model boards and the host's
shared browser: a proxy that refuses every connection stands in for both, and only the Home's
sink, where a test set one, is reached directly.

`midday(home)` puts the Home in a zone where it is midday now, so a test's ticks fall on one
local day, and returns that zone for the test to read the times ak writes.

    from fixtures.akbin import Home
    from fixtures.loginend import Logins, tick
    with Home() as home:
        logins = Logins(home)
        logins.answer("default", "owner@acme.test", 1792700000)
        tick(home)
        assert logins.asked() == [""]
"""

from datetime import timedelta, timezone
import json
import shlex
import socket
import time
from urllib.parse import urlsplit

SCRIPT = """#!/bin/sh
printf '%s:%s\\n' "$1" "${{AGENTKIT_ACCOUNT-}}" >>{log}
[ "$1" = login-end ] || exit 2
exec cat {answers}/"${{AGENTKIT_ACCOUNT:-default}}.json"
"""
# Bound and never listening, so every connection to it is refused, and no other program can
# take its port while this one runs.
_REFUSER = socket.socket()
_REFUSER.bind(("127.0.0.1", 0))
REFUSED = f"http://127.0.0.1:{_REFUSER.getsockname()[1]}"


class Logins:
    def __init__(self, home, harness="claude"):
        directory = home.root / "adapters"
        self.answers, self.log = directory / f"{harness}-login-end", directory / f"{harness}.log"
        self.answers.mkdir(parents=True)
        script = directory / f"{harness}.sh"
        script.write_text(SCRIPT.format(log=shlex.quote(str(self.log)),
                                        answers=shlex.quote(str(self.answers))))
        script.chmod(0o755)
        home.env["AGENTKIT_ADAPTER_DIR"] = str(directory)

    def answer(self, account, email, ends):
        """What that account's `login-end` prints from now on: whose login, and the epoch
        second it ends, either None."""
        (self.answers / f"{account}.json").write_text(json.dumps({"email": email, "ends": ends}))

    def asked(self):
        try:
            calls = self.log.read_text().splitlines()
        except FileNotFoundError:
            return []
        return [call.split(":", 1)[1] for call in calls if call.startswith("login-end:")]


def tick(home):
    """One `ak watch`, which must succeed."""
    sink = urlsplit(home.env.get("AK_NOTIFY_SINK") or "").netloc
    env = {name: REFUSED for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
    done = home.ak("watch", env={**env, "no_proxy": sink, "NO_PROXY": sink})
    assert done.code == 0, done.err
    return done


def midday(home):
    hours = (24 - time.gmtime().tm_hour) % 24 - 12
    home.env["TZ"] = f"AKT{-hours:+d}"      # POSIX counts west of UTC: AKT-5 is five hours ahead
    return timezone(timedelta(hours=hours))
