"""A harness's `login-end` answered per account, and a tick that must succeed.

`Logins(home)` puts `<harness>.sh` in a directory the Home's AGENTKIT_ADAPTER_DIR names, in
place of that harness's adapter.  Its `login-end` prints what `answer` set for the account
AGENTKIT_ACCOUNT names (`default` where it names none) and fails for an account given no
answer; every other verb fails, as an adapter with nothing to say.  `asked()` is the
AGENTKIT_ACCOUNT of each `login-end` call so far, oldest first, "" where it named none.

`tick(home)` runs one `home.tick()`, which must exit 0; `kept(home)` is what ak kept of each
login, in state/logins.json, and `events(home)` each event its outbox holds.

`midday(home)` puts the Home in a zone where it is midday now, so a test's ticks fall on one
local day, and returns that zone for the test to read the times ak writes.
"""

from datetime import timedelta, timezone
import json
import shlex
import time

SCRIPT = """#!/bin/sh
printf '%s:%s\\n' "$1" "${{AGENTKIT_ACCOUNT-}}" >>{log}
[ "$1" = login-end ] || exit 2
exec cat {answers}/"${{AGENTKIT_ACCOUNT:-default}}.json"
"""


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

    def answer(self, account, email, ends, plan=None):
        """What that account's `login-end` prints from now on: whose login, the epoch second it
        ends and the plan it is on, each maybe None."""
        (self.answers / f"{account}.json").write_text(
            json.dumps({"email": email, "ends": ends, "plan": plan}))

    def asked(self):
        try:
            calls = self.log.read_text().splitlines()
        except FileNotFoundError:
            return []
        return [call.split(":", 1)[1] for call in calls if call.startswith("login-end:")]


def tick(home):
    done = home.tick()
    assert done.code == 0, done.err
    return done


def kept(home):
    return json.loads((home.path / ".agentkit/state/logins.json").read_text())


def events(home):
    return [json.loads(path.read_text()) for path in
            (home.path / ".agentkit/state/notification-outbox").glob("*.json")]


def midday(home):
    hours = (24 - time.gmtime().tm_hour) % 24 - 12
    home.env["TZ"] = f"AKT{-hours:+d}"      # POSIX counts west of UTC: AKT-5 is five hours ahead
    return timezone(timedelta(hours=hours))
