"""A login parked by a refusal is used again once an asked reading shows its meter has fallen.

Anthropic's usage-limit reset refills a login inside its weekly window without moving `resets_at`.
Once a probe after the refusal reads the named meter lower by more than a point of jitter, with
room left, the mark ends: `ak usage` says the login has room and a worker is picked on it.  A
reading at the refusal's level, or one point below it, ends no mark.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py.
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

OFFLINE = {"https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
           "GIT_ALLOW_PROTOCOL": "file"}
WEEK = 604800
DAYS_AWAY = 3 * 86400


def staged(case):
    home = Home()
    case.addCleanup(home.close)
    home.env.update(OFFLINE)
    rig = Rig(home, "widgets")
    fake = fakeadapter.install(home, claude="pass")["claude"]
    akconfig.write(home, {"acme": {"harness": "claude"}},
                   providers={"anthropic": {"mode": "subscription"}})
    return home, rig, fake, int(time.time()) + DAYS_AWAY


def feed(home, fake, used, resets_at):
    """Set what `<adapter> usage` answers next, and let the next pass ask it."""
    fake.answer("usage", json.dumps({"meters": [
        {"name": "weekly_all", "used": used, "resets_at": resets_at, "window_secs": WEEK}],
        "error": None}))
    snapshot = home.path / ".agentkit/state/usage.json"
    if snapshot.exists():
        blob = json.loads(snapshot.read_text())
        blob["fetched_at"] = 0
        snapshot.write_text(json.dumps(blob))
    (home.path / ".agentkit/state/anthropic-probe.lock").parent.mkdir(parents=True, exist_ok=True)
    (home.path / ".agentkit/state/anthropic-probe.lock").write_text("0")


class RefilledLoginIsUsedAgain(unittest.TestCase):
    def test_a_refilled_claude_login_has_room_and_runs_a_worker(self):
        home, rig, fake, resets_at = staged(self)
        feed(home, fake, 98, resets_at)
        events = json.dumps({"type": "rate_limit_event", "rate_limit_info": {
            "status": "rejected", "unifiedWindows": {
                "seven_day": {"utilization": 1.0, "resetsAt": resets_at}}}}) + "\n"
        fake.behave({"events": events,
                     "final": f"You've hit your limit · resets {{in {DAYS_AWAY}}}", "exit": 1})
        refused = home.ak("run", str(taskfile.write(home, rig.path, "First task")), "--no-merge",
                          timeout=120)
        self.assertEqual(refused.code, 1, refused.out + refused.err)

        feed(home, fake, 100, resets_at)
        spent = home.ak("usage", "--json")
        self.assertEqual(spent.code, 0, spent)
        spent_json = json.loads(spent.out)
        self.assertTrue(spent_json["providers"]["anthropic"]["exhausted"])
        self.assertEqual(spent_json["pick_order"], [])

        feed(home, fake, 76, resets_at)
        refilled = home.ak("usage", "--json")
        self.assertEqual(refilled.code, 0, refilled)
        refilled_json = json.loads(refilled.out)
        self.assertFalse(refilled_json["providers"]["anthropic"]["exhausted"])
        self.assertEqual([m["used"] for m in refilled_json["providers"]["anthropic"]["meters"]],
                         [76])
        self.assertEqual(refilled_json["pick_order"], ["acme"])
        screen = home.ak("--dry-run", env={"NO_COLOR": "1"})
        self.assertEqual(screen.code, 0, screen)
        self.assertIn("24% left", screen.out)

        fake.behave("work")
        built = home.ak("run", str(taskfile.write(home, rig.path, "Second task")), "--no-merge",
                        timeout=120)
        self.assertEqual(built.code, 0, built.out + built.err)
        self.assertEqual(fake.n, 3)

    def test_a_login_refused_at_97_stays_parked_at_97_and_96(self):
        home, rig, fake, resets_at = staged(self)
        feed(home, fake, 97, resets_at)
        fake.behave({"final": f"You've hit your limit · resets {{in {DAYS_AWAY}}}", "exit": 1})
        refused = home.ak("run", str(taskfile.write(home, rig.path, "Refused at 97")),
                          "--no-merge", timeout=120)
        self.assertEqual(refused.code, 1, refused.out + refused.err)

        for used in (97, 96):
            with self.subTest(used=used):
                feed(home, fake, used, resets_at)
                shown = home.ak("usage", "--json")
                self.assertEqual(shown.code, 0, shown)
                data = json.loads(shown.out)
                self.assertTrue(data["providers"]["anthropic"]["exhausted"])
                self.assertEqual(data["pick_order"], [])
                still = home.ak("run", str(taskfile.write(home, rig.path, f"Still {used}")),
                                "--no-merge", timeout=120)
                self.assertEqual(still.code, 1, still.out + still.err)
                self.assertEqual(fake.n, 1)


if __name__ == "__main__":
    unittest.main()
