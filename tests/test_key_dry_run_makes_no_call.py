"""A quota refusal during a landing fix waits for its executor, despite a pending review.

Black-box through AK_BIN: main moves while the reviewer runs, its rebase fixer refuses for an
hour, and neither an explicit resume nor ticks may spend another turn before that reset.  Time
passes by the records, not by the program's clock: between ticks each stamp a tick compares
with now is set back by the time passed.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, boxable
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_exhausted_resume import OFFLINE, record, tick, wait_for

REFUSED = {"final": "You've hit your 5-hour limit · resets {in 3600}", "exit": 1}
RESOLVE = {"sh": "printf 'main\\nhello\\n' > retry.txt && git add retry.txt && "
                 "GIT_EDITOR=true git rebase --continue",
           "final": "Resolved.", "hand_in": [["done"]]}


def back(stamps, key, seconds):
    """`stamps[key]`, where there is one, `seconds` earlier."""
    if key in stamps:
        stamps[key] -= seconds


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class DryRunMakesNoCall(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        home.env.update(OFFLINE)
        self.rig = rig = Rig(home, "widgets")
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        self.fakes = fakeadapter.install(home, claude="work", codex="pass")
        worker = self.fakes["claude"]
        held, go = worker.dir / "held", worker.dir / "go"
        worker.behave("work", REFUSED, RESOLVE)
        self.fakes["codex"].behave({**fakeadapter.PASS, "sh": f"touch {held}; "
                                    f"until test -f {go}; do sleep 0.1; done"})
        week = {"name": "weekly", "used": 10, "resets_at": int(time.time()) + 86400,
                "window_secs": 604800}
        for fake in self.fakes.values():
            fake.answer("usage", json.dumps({"meters": [week], "error": None}))
        running = home.spawn("run", str(taskfile.write(home, rig.path)))
        wait_for(held.exists, "reviewer waiting for main")
        rig.commit({"retry.txt": "main\n"}, "main moves")
        go.touch()
        self.assertEqual(running.wait(timeout=120), 1, home.log("spawn-1.out").read_text())
        self.directory = taskfile.only_run(home)
        state = record(self.directory)
        self.assertEqual(state["state"], "exhausted")
        self.assertTrue(state["review_pending"])
        self.assertIs(state["review_pending"]["record"], False)
        self.assertEqual(state["step"], "executor")
        self.assertEqual(worker.n, 2)

    def snapshot(self):
        state = record(self.directory)
        return (state["state"], state["slot_started_at"], state["round_summaries"],
                sorted(str(p.relative_to(self.directory))
                       for p in self.directory.glob("round-*/**") if p.is_dir()),
                {name: fake.n for name, fake in self.fakes.items()})

    def test_manual_resume_and_ticks_wait_without_a_slot_or_turn_until_reset(self):
        before = self.snapshot()
        resumed = self.home.ak("run", "resume", self.directory.name)
        self.assertEqual(resumed.code, 1, resumed.out + resumed.err)
        cache = json.loads((self.home.path / ".agentkit/state/usage.json").read_text())
        until = cache["providers"]["anthropic"]["exhausted_until"]
        self.assertIn(time.strftime("%Y-%m-%d %H:%M", time.gmtime(until)), resumed.out)
        self.assertEqual(self.snapshot(), before)
        background = self.home.ak("run", "resume", self.directory.name, "--bg")
        self.assertEqual(background.code, 1, background.out + background.err)
        self.assertEqual(self.snapshot(), before)
        self.check_ticks_and_reset(before)

    def test_ticks_alone_wait_for_the_executor_even_with_a_pending_review(self):
        self.check_ticks_and_reset(self.snapshot())

    def later(self, seconds):
        """`seconds` pass for the stamps a tick compares with now: each is set back by them."""
        cache = self.home.path / ".agentkit/state/usage.json"
        usage = json.loads(cache.read_text())
        for provider in usage["providers"].values():
            back(provider, "exhausted_until", seconds)
        cache.write_text(json.dumps(usage))
        state = record(self.directory)
        back(state, "exhausted_resume_at", seconds)
        back(state.get("refusal_retry") or {}, "at", seconds)
        (self.directory / "run.json").write_text(json.dumps(state))

    def check_ticks_and_reset(self, before):
        for _ in range(3):      # ten, twenty and thirty minutes on, each past a resume's wait
            self.later(601)
            tick(self.home)
            self.assertEqual(self.snapshot(), before)
        self.later(3601 - 3 * 601)  # a second past the hour to the reset
        tick(self.home)
        state = record(self.directory)
        self.assertEqual(state["state"], "pass", (self.directory / "log.txt").read_text())
        self.assertTrue(state["merged"])
        self.assertEqual(self.fakes["claude"].n, 3)


if __name__ == "__main__":
    unittest.main()
