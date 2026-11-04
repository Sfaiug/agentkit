"""A live project's merge wakes its seat once, with the change going live.

Black-box: AK_BIN, a Home, git Rig, fake GitHub, Seat and notification Sink.
The health command fails until the test creates live-ready.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.sink import Sink

RUN = "20261104-1000-acme-api"
HEALTH = 'test -e "$HOME/live-ready"'


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class LiveHostWakesOnce(unittest.TestCase):
    def case(self, *, health=True, other=True, linked=True, wait=True):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus", "astra"])
        fakeadapter.install(self.home, claude="pass", codex="pass")
        self.sink = Sink(self.home)
        self.addCleanup(self.sink.close)
        declaration = f"health: {HEALTH}\n" if health else ""
        self.rig = Rig(self.home, "widget", files={"AGENTS.md": f"---\n{declaration}---\n"})
        github = GitHub(self.home)
        self.seat = Seat(self.home, "acme", cwd=self.rig.path, planned=True,
                         record={"repo": str(self.rig.path)})
        sha = self.rig.branch("fix-api", {"api.txt": "ready\n"})
        pr = github.open_pr(self.rig, "fix-api", title="Acme api")
        state = {"run_id": RUN, "title": "Acme api", "state": "waiting",
                 "waiting_on": {"line": self.rig.slug}, "repo": str(self.rig.path),
                 "launched_session": self.seat.name, "pr": pr,
                 "executor": "opus", "reviewer": "astra",
                 "review": {"executor": "opus", "reviewer": "astra",
                            "executor_provider": "anthropic", "reviewer_provider": "openai",
                            "verdict": "PASS", "returncode": 0, "done_when": True,
                            "head_sha": sha, "tree_sha": self.rig.git("rev-parse", f"{sha}^{{tree}}")}}
        self.relative = f".agentkit/runs/{RUN}/run.json"
        self.home.write(self.relative, state)
        if other:
            self.home.write(".agentkit/runs/acme-web/run.json", {
                "run_id": "acme-web", "state": "waiting", "repo": str(self.rig.path),
                "waiting_on": {"line": self.rig.slug}, "launched_session": self.seat.name,
                "plan_line": "The work is done · written 2026-10-23 09:00" if linked else None})
        if wait:
            done = self.home.ak("wait", RUN, env={"AGENTKIT_SESSION": self.seat.name})
            self.assertEqual(done.code, 0, done.out + done.err)
        done = self.home.run("gh", "pr", "merge", pr, "--squash", cwd=self.rig.path)
        self.assertEqual(done.code, 0, done.out + done.err)
        state.pop("waiting_on")
        state.update(state="pass", verdict="PASS", merged=True, finished_at=time.time(),
                     merge_sha=github.pr(1)["merge"]["commit"], deployed=None,
                     health={"command": HEALTH} if health else {})
        self.home.write(self.relative, state)
        self.tick()

    def tick(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.sink.pages(), [])

    def heard(self, *, live=False):
        lines = self.seat.wait_lines(1)
        self.assertEqual(len(lines), 1, lines)
        line, = lines
        self.assertIn(f"run {RUN} finished PASS", line)
        self.assertIn("merged", line)
        if live:
            self.assertIn(f"run {RUN} is live:", line)
        self.tick()
        self.assertEqual(self.seat.lines(), [line])

    def test_a_named_merge_waits_for_health_and_is_told_with_live_once(self):
        self.case()
        self.assertEqual(self.seat.typed(), "")
        wait = json.loads((self.home.path / ".agentkit/state/seat-acme.json").read_text())["wait"]
        self.assertNotIn("over", wait)
        state = json.loads((self.home.path / self.relative).read_text())
        self.assertNotIn("live_at", state)
        self.assertIn("output", state["health"])
        self.home.write("live-ready", "")
        self.tick()
        self.heard(live=True)

    def test_without_health_the_merge_is_told_at_once(self):
        self.case(health=False)
        self.heard()

    def test_the_last_run_waits_for_live_without_an_explicit_wait(self):
        self.case(other=False, wait=False)
        self.assertEqual(self.seat.typed(), "")
        self.home.write("live-ready", "")
        self.tick()
        self.seat.show("claude-working-pane.txt")
        self.heard(live=True)

    def test_an_unserved_line_wakes_the_seat_at_the_merge(self):
        self.case(linked=False)
        self.heard()

    def test_the_detached_follower_delivers_the_combined_line_without_a_tick(self):
        self.case()
        self.assertEqual(self.seat.typed(), "")
        self.home.write("live-ready", "")
        done = self.home.ak("watch", "--live", RUN)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.heard(live=True)


if __name__ == "__main__":
    unittest.main()
