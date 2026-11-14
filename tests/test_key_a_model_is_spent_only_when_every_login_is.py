"""A model is spent on a provider only when it is spent on every login a turn of it runs on.

A Claude login reads a week every model draws on (`weekly_all`) and a cap that is Fable's alone
(`weekly_scoped`, scope `Fable`).  A provider listing `accounts` is read off the login ranked
first on every model's meters, so a login whose week is spent ranks with one whose Fable cap is:
Opus was called spent on the provider and never picked, though a turn of it runs on a login
with week left.

Black-box: AK_BIN in a temporary HOME with Claude's provider listing the logins given, injected
usage readings and a scripted adapter; a turn's login is the AGENTKIT_ACCOUNT its adapter call
is told, as tests/test_key_seat_account_last.py reads it.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

OPUS, FABLE = "claude-opus-5-5", "claude-fable-5-2"


class SpentOnlyWhenEveryLoginIs(unittest.TestCase):
    def pick(self, *, run=False, **used):
        """(`ak usage --json`'s pick_order, the login an executor turn of a run ran on, or None
        without `run`) over logins each given (week, Fable cap)% used, two workers naming no
        `meter`."""
        with Home() as home:
            rig = Rig(home)
            akconfig.write(home, {model: "claude" for model in (OPUS, FABLE)},
                           providers={"anthropic": {"accounts": list(used)}})
            assert not any("meter" in entry for entry in akconfig.read(home)["models"].values())
            home.fake("claude", "#!/bin/sh\nexit 0\n")
            fake = fakeadapter.install(home, claude="work")["claude"]
            now = time.time()

            def reading(week, cap):
                meter = {"used": week, "window_secs": 604800, "resets_at": now + 3 * 86400}
                return {"provider": "anthropic", "resets": 0, "meters": [
                    {**meter, "name": "weekly_all"},
                    {**meter, "name": "weekly_scoped", "scope": "Fable", "used": cap}]}

            accounts = {login: reading(*pair) for login, pair in used.items()}
            home.write(".agentkit/state/usage.json", {
                "fetched_at": now, "reset_checked_at": now, "providers": {"anthropic": {
                    **accounts["default"], "accounts": accounts}}})
            shown = home.ak("usage", "--json")
            self.assertEqual(shown.code, 0, shown.out + shown.err)
            order = json.loads(shown.out)["pick_order"]
            if not run:
                return order, None
            done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            turns = [call for call in fake.runs() if call["role"] == "executor"]
            self.assertEqual([call["argv"][0] for call in turns], [OPUS])
            return order, turns[0]["env"].get("AGENTKIT_ACCOUNT") or "default"

    def test_a_week_left_on_another_login_leaves_the_model_picked(self):
        self.assertEqual(self.pick(run=True, default=(100, 57), second=(82, 100)),
                         ([OPUS], "second"))
        self.assertEqual(self.pick(run=True, default=(100, 10), second=(100, 20),
                                   third=(50, 100)), ([OPUS], "third"))

    def test_room_on_the_login_read_stands_whatever_the_others_read(self):
        self.assertEqual(self.pick(default=(40, 100), second=(100, 10)), ([OPUS], None))

    def test_spent_on_every_login_is_spent(self):
        self.assertEqual(self.pick(default=(100, 100), second=(100, 100)), ([], None))


if __name__ == "__main__":
    unittest.main()
