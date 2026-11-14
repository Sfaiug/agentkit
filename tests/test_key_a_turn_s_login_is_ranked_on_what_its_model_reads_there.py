"""A worker turn's login is ranked on what its model reads there.

A Claude login reads a week every model draws on (`weekly_all`) and a cap that is Fable's alone
(`weekly_scoped`, scope `Fable`).  A login whose Fable cap is spent still has the week for Opus:
an Opus turn ranked it with the logins that have nothing left and ran on the usual login, the
one kept for last.

Black-box: AK_BIN runs a task in a temporary HOME with an invented provider of three logins,
injected usage readings and a scripted adapter; a turn's login is the AGENTKIT_ACCOUNT its
adapter call is told, as tests/test_key_seat_account_last.py reads it.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

OPUS, FABLE = "claude-opus-5-5", "claude-fable-5-2"


class RankedOnItsModel(unittest.TestCase):
    def logins(self, **used):
        """{model: the logins its worker turns ran on} for one run Opus executes and Fable
        reviews, each login's week and Fable cap `used` as (week, cap)% used, or (week, cap,
        opus) beside a cap of Opus's own by the same name, two workers naming no `meter`.  The
        two are named outright: what a turn's login is, not whether the pick lets the model
        run."""
        with Home() as home:
            rig = Rig(home)
            akconfig.write(home, {model: {"harness": "acme", "provider": "acme"}
                                  for model in (OPUS, FABLE)},
                           providers={"acme": {"accounts": list(used)}})
            assert not any("meter" in entry for entry in akconfig.read(home)["models"].values())
            home.fake("acme", "#!/bin/sh\nexit 0\n")
            fake = fakeadapter.install(home, acme="work")["acme"]
            now = time.time()

            def reading(week, cap, *opus):
                meter = {"used": week, "window_secs": 604800, "resets_at": now + 3 * 86400}
                return {"provider": "acme", "resets": 0, "meters": [
                    {**meter, "name": "weekly_all"},
                    {**meter, "name": "weekly_scoped", "scope": "Fable", "used": cap},
                    *({**meter, "name": "weekly_scoped", "scope": "Opus", "used": used}
                      for used in opus)]}

            accounts = {login: reading(*pair) for login, pair in used.items()}
            home.write(".agentkit/state/usage.json", {
                "fetched_at": now, "reset_checked_at": now, "providers": {"acme": {
                    **accounts["default"], "accounts": accounts}}})
            done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge",
                           "--exec", OPUS, "--review", FABLE, timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            ran = {}
            for call in fake.runs():
                ran.setdefault(call["argv"][0], set()).add(
                    call["env"].get("AGENTKIT_ACCOUNT") or "default")
            return ran

    def test_another_models_spent_cap_leaves_a_login_the_week(self):
        ran = self.logins(default=(10, 10), second=(30, 100), third=(100, 20))
        self.assertEqual(ran, {OPUS: {"second"}, FABLE: {"default"}})

    def test_the_week_left_is_what_an_opus_turn_reads(self):
        ran = self.logins(default=(100, 10), second=(100, 20), third=(50, 100))
        self.assertEqual(ran[OPUS], {"third"})


if __name__ == "__main__":
    unittest.main()
