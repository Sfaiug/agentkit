"""Another model leaves a login the part of its week held for a cap.

A Claude login's kept reading holds its shared week (`weekly_all`) and Fable's own cap
(`weekly_scoped`, scope `Fable`), which carries `held`: the points of that week held for it.  To
any other model the week reads as used by that part as well, `min(100, used + held)`, so Opus
is spent where only Fable's part is left, and its reason says the week as read and whose the
rest is.  Fable reads the week as it is, and so do `ak usage --json` and a cap holding nothing.

The owner (26 Nov 2026): "ideally we want all to run out when both fable and other model usage
are at 0. Fable should not still have usage left".

Black-box: AK_BIN in a temporary HOME with Claude's provider listing the logins given, their
readings in state/usage.json and a scripted adapter; a turn's login is the AGENTKIT_ACCOUNT its
adapter call is told, as tests/test_key_a_model_is_spent_only_when_every_login_is.py reads it.
Fails against /bin/false.
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


class AnotherModelLeavesACapsPart(unittest.TestCase):
    def usage(self, *, run=False, **logins):
        """(`ak usage --json`'s output, what `ak usage` printed to stderr, the login an executor
        turn of Opus ran on, or None without `run`) over logins each given (week used, points
        its Fable cap holds or None), Opus and Fable the workers unless `run`, which marks
        Opus alone."""
        with Home() as home:
            rig = Rig(home)
            akconfig.write(home, {model: "claude" for model in (OPUS, FABLE)},
                           workers=[OPUS] if run else None,
                           providers={"anthropic": {"accounts": list(logins)}})
            home.fake("claude", "#!/bin/sh\nexit 0\n")
            fake = fakeadapter.install(home, claude="work")["claude"]
            now = time.time()

            def reading(week, held):
                meter = {"window_secs": 604800, "resets_at": now + 3 * 86400, "elapsed": 57}
                cap = {**meter, "name": "weekly_scoped", "scope": "Fable", "used": 20}
                return {"provider": "anthropic", "resets": 0, "meters": [
                    {**meter, "name": "weekly_all", "used": week},
                    {**cap, "held": held} if held is not None else cap]}

            accounts = {login: reading(*pair) for login, pair in logins.items()}
            home.write(".agentkit/state/usage.json", {
                "fetched_at": now, "reset_checked_at": now, "providers": {"anthropic": {
                    **accounts["default"], "accounts": accounts}}})
            shown, told = home.ak("usage", "--json"), home.ak("usage")
            self.assertEqual(shown.code, 0, shown.out + shown.err)
            self.assertEqual(told.code, 0, told.out + told.err)
            if not run:
                return json.loads(shown.out), told.err, None
            done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            turns = [call for call in fake.runs() if call["role"] == "executor"]
            self.assertEqual([call["argv"][0] for call in turns], [OPUS])
            return (json.loads(shown.out), told.err,
                    turns[0]["env"].get("AGENTKIT_ACCOUNT") or "default")

    def test_a_week_used_but_for_the_held_part_is_spent_for_another_model_alone(self):
        shown, said, _ = self.usage(default=(60, 40))
        self.assertEqual(shown["pick_order"], [FABLE])
        self.assertIn(f"pick executor: {OPUS} excluded: weekly_all 60% used, the rest held "
                      "for Fable", said)
        shown, _, _ = self.usage(default=(59, 40))
        self.assertEqual(sorted(shown["pick_order"]), sorted([OPUS, FABLE]))

    def test_a_turn_of_another_model_goes_to_the_login_with_room_past_the_held_part(self):
        # read as it is, the spare login with 40% left goes before the usual one with 20%
        _, _, login = self.usage(run=True, default=(80, None), second=(60, 40))
        self.assertEqual(login, "default")

    def test_a_login_whose_cap_holds_nothing_reads_as_today(self):
        shown, _, _ = self.usage(default=(99, None))
        self.assertEqual(sorted(shown["pick_order"]), sorted([OPUS, FABLE]))
        _, _, login = self.usage(run=True, default=(80, None), second=(60, None))
        self.assertEqual(login, "second")

    def test_ak_usage_json_gives_the_week_as_read(self):
        shown, _, _ = self.usage(default=(60, 40))
        meters = {m["name"]: m for m in shown["providers"]["anthropic"]["meters"]}
        self.assertEqual(meters["weekly_all"]["used"], 60)
        self.assertFalse(meters["weekly_all"]["exhausted"])
        self.assertEqual(meters["weekly_scoped"]["held"], 40)
        self.assertFalse(shown["providers"]["anthropic"]["exhausted"])


if __name__ == "__main__":
    unittest.main()
