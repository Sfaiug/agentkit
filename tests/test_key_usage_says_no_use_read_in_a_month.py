"""A paid login of a provider a role marks says `no use read in a month` after its price in
`ak usage`'s `a month` cell, in the table and on a narrow card alike, and is `no_use_read` true in
`ak usage --json`, where the readings ak keeps of the meter that is its shared week now begin a
month (52/12 weeks) or more before the usage clock and none taken in that month reads above 0
used.  A week in the middle nobody read changes nothing: ak says only what it read; nor does a
model's own cap of the meter's name (`scope`), nor a reading taken after the usage clock.  One
with a reading above 0 in the month, one whose oldest reading is a week old and two with no
shared week over a month of readings at 0, one whose probe reads no meter now and one whose
probe reads its 5h session alone (the owner, 24 Nov 2026: "Leave it"), read as today and are
`no_use_read` false; one no role marks keeps `no role marks its models`.

Black-box, as tests/test_key_usage_says_a_plan_no_role_marks.py is and on its fixtures, with
invented logins and readings written into its Home, the readings dated back from the moment its
usage clock stands at (`AK_USAGE_CLOCK`, tests/fixtures/clock.py).  Fails against /bin/false.
"""

from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, clock, meters
from fixtures.akbin import Home
import test_key_usage_says_a_plan_no_role_marks as marks
from test_key_week_price import METER_READINGS

NOW = int(time.time())
HOUR, DAY, WEEK, SESSION = 3600, 86400, 7 * 86400, 5 * 3600
# (provider, account): (its row on `ak usage`, its plan, its one meter's window, the days
# before NOW that meter was read on, the day of those it read 3% used or None).  Five weeks are
# kept at most.  Two have no shared week: Grok's meter is its 5h session, and Claude III's probe
# reads no meter now.
LOGINS = {("anthropic", "default"): ("Claude I", "max 20x", WEEK, range(35), None),
          ("anthropic", "second"): ("Claude II", "pro", WEEK, [*range(14), *range(21, 35)], None),
          ("anthropic", "third"): ("Claude III", "max 5x", WEEK, range(35), None),
          ("openai", "default"): ("ChatGPT", "pro", WEEK, range(35), 10),
          ("google", "default"): ("Gemini", "Google AI Pro", WEEK, range(8), None),
          ("xai", "default"): ("Grok", "X Premium", SESSION, range(35), None)}
# No reading of a shared week in the month, (provider, account, used, at, scope) each: Anvil's own
# caps of the meter's name, and a reading taken after NOW.
NOT_THE_MONTH = [("anthropic", "default", 7, NOW - DAY // 2, "anvil"),
                 ("anthropic", "second", 5, NOW + 60, None),
                 ("google", "default", 0, NOW - 33 * DAY, "anvil")]


def resets_at(day, window):
    """When the window resets that its meter was read in `day` days before NOW: a week a day
    after NOW or whole weeks before that, a session an hour after the reading."""
    return NOW + DAY - day // 7 * WEEK if window == WEEK else NOW - day * DAY + HOUR


class UsageSaysNoUseReadInAMonth(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        clock.standing(self.home, "AK_USAGE_CLOCK", NOW)
        meter = meters.install(self.home)
        for harness in ("claude", "codex", "antigravity", "grokbuild"):
            shutil.copy2(meter.dir / "echo.sh", meter.dir / f"{harness}.sh")
        logins = {}
        for (provider, account), (_, plan, window, _, _) in LOGINS.items():
            logins.setdefault(provider, {})[account] = {
                "email": f"{account}@{provider}.test", "ends": None, "plan": plan,
                "checked_at": NOW}
            if (provider, account) != ("anthropic", "third"):   # its probe reads no meter now
                meter.week(provider, account, used=0, window=window,
                           resets_at=resets_at(0, window))
        self.home.write(".agentkit/state/logins.json", logins)
        with closing(sqlite3.connect(self.home.path / ".agentkit/history.db")) as db, db:
            db.execute(METER_READINGS)
            db.execute("ALTER TABLE meter_readings ADD COLUMN scope TEXT")
            # each reading inside its window (`resets_at`), as the probe's now is
            db.executemany(f"INSERT INTO meter_readings VALUES ({', '.join('?' * 10)})", [
                *((provider, account, "weekly", 3 if day == spent else 0,
                   resets_at(day, window), window, NOW - day * DAY, "probe", plan, None)
                  for (provider, account), (_, plan, window, days, spent) in LOGINS.items()
                  for day in days),
                *((provider, account, "weekly", used, at + DAY, WEEK, at, "probe",
                   LOGINS[provider, account][1], scope)
                  for provider, account, used, at, scope in NOT_THE_MONTH)])

    def usage(self, *, orchestrator="anvil", workers=tuple(marks.MODELS)):
        """Each login's (`price`, `marked` and `no_use_read` on `ak usage --json`, `a month` in
        the table and on a narrow card)."""
        akconfig.write(self.home, marks.MODELS, orchestrator=orchestrator, workers=list(workers),
                       providers={name: {"mode": "subscription",
                                         **({"accounts": ["default", "second", "third"]}
                                            if name == "anthropic" else {})}
                                  for name in marks.PLANS})
        data = self.home.ak("usage", "--json")
        self.assertEqual(data.code, 0, data.out + data.err)
        found = json.loads(data.out)["providers"]
        wide, narrow = (self.home.ak("usage", env=env) for env in (marks.WIDE, marks.NARROW))
        for text in (wide, narrow):
            self.assertEqual(text.code, 0, text.out + text.err)
        got = {}
        for (provider, account), (label, *_) in LOGINS.items():
            record = found[provider]["accounts"][account] if provider == "anthropic" \
                else found[provider]
            got[provider, account] = (record["price"], record["marked"], record["no_use_read"],
                                      meters.cell(wide.out, label, "a month"),
                                      marks.card_month(narrow.out, label))
        return got

    def test_only_a_month_of_readings_showing_nothing_used_says_so(self):
        self.assertEqual(self.usage(), {
            ("anthropic", "default"): (200, True, True, "$200 · no use read in a month",
                                       "$200 · no use read in a month"),
            ("anthropic", "second"): (20, True, True, "$20 · no use read in a month",
                                      "$20 · no use read in a month"),
            ("anthropic", "third"): (100, True, False, "$100", "$100"),
            ("openai", "default"): (200, True, False, "$200", "$200"),
            ("google", "default"): (19.99, True, False, "$19.99", "$19.99"),
            ("xai", "default"): (8, True, False, "$8", "$8")})

    def test_a_login_no_role_marks_says_that_instead(self):
        got = self.usage(orchestrator="bolt", workers=("bolt", "crux", "dart"))
        self.assertEqual(got["anthropic", "default"],
                         (200, False, False, "$200 · no role marks its models",
                          "$200 · no role marks its models"))


if __name__ == "__main__":
    unittest.main()
