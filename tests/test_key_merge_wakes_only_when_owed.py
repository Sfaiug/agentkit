"""A delivered run wakes its seat only when the seat has a next move waiting on it.

Black-box: AK_BIN checks the plan and offers endings beside two linked runs and an
explicit wait, with Home, a git Rig, fake GitHub and a seat backed by fakeadapter.
"""

import json
import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

RUNS = {part: f"20261104-0900-acme-{part}" for part in ("api", "web")}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class MergeWakesOnlyWhenOwed(unittest.TestCase):
    def case(self, part, passes, model, linked=True):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra", "grok"])
        fakeadapter.install(home, claude="pass", codex="pass", grokbuild="pass")
        rig, github = Rig(home, "acme"), GitHub(home)
        seat = Seat(home, "acme", cwd=rig.path, model=model, record={"repo": str(rig.path)},
                    screen="grok-prompt-pane.txt" if model == "grok" else "claude-prompt-pane.txt")

        def ak(*args):
            done = home.ak(*args, cwd=rig.path, env={"AGENTKIT_SESSION": seat.name})
            self.assertEqual(done.code, 0, done.out + done.err)
            return done.out

        states = {}
        for item, run in RUNS.items():
            ak("plan", "add", f"acme {item}", "--check", f"test -f {item}.txt")
            sha = rig.branch(item, {f"{item}.txt": item + "\n"})
            pr = github.open_pr(rig, item, title=f"acme {item}")
            text = (home.path / ".agentkit/state/plan-acme.md").read_text()
            written = re.search(rf"acme {item} · .* · written (\d{{4}}-\d\d-\d\d \d\d:\d\d)", text)
            self.assertIsNotNone(written, text)
            states[item] = {"run_id": run, "title": f"acme {item}", "state": "waiting",
                            "waiting_on": {"line": rig.slug}, "repo": str(rig.path),
                            "launched_session": seat.name, "pr": pr,
                            "executor": "opus", "reviewer": "astra",
                            "review": {"executor": "opus", "reviewer": "astra",
                                       "executor_provider": "anthropic", "reviewer_provider": "openai",
                                       "verdict": "PASS", "returncode": 0, "done_when": True,
                                       "head_sha": sha, "tree_sha": rig.git("rev-parse", f"{sha}^{{tree}}")},
                            "plan_line": f"acme {item} · written {written[1]}" if linked else None}
            home.write(f".agentkit/runs/{run}/run.json", states[item])
        ak("wait", RUNS["api"])
        if not passes:
            ak("plan", "check", "2", "test -f web-ready.txt")
        done = home.run("gh", "pr", "merge", states[part]["pr"], "--squash", cwd=rig.path)
        self.assertEqual(done.code, 0, done.out + done.err)
        states[part].pop("waiting_on")
        states[part].update(state="pass", verdict="PASS", merged=True, finished_at=time.time(),
                            merge_sha=github.pr(1 if part == "api" else 2)["merge"]["commit"])
        home.write(f".agentkit/runs/{RUNS[part]}/run.json", states[part])
        # Delivery's plan checks settle before the wake decision.
        ak("plan")
        plan = (home.path / ".agentkit/state/plan-acme.md").read_text()
        self.assertIn(f"- [{'x' if passes else ' '}] acme {part} ·", plan)
        tick = home.tick()
        self.assertEqual(tick.code, 0, tick.out + tick.err)
        return home, seat, ak

    def test_b_merges_while_a_serves_every_line_still_owed(self):
        for model in ("opus", "grok"):
            with self.subTest(model=model):
                home, seat, ak = self.case("web", True, model)
                self.assertEqual(seat.typed(), "")
                status = ak("run", "status", RUNS["web"])
                self.assertIn(f"run {RUNS['web']} finished PASS", status)
                self.assertIn("merged", status)
                tick = home.tick()
                self.assertEqual(tick.code, 0, tick.out + tick.err)
                self.assertEqual(seat.typed(), "")

    def test_a_merges_and_ends_the_explicit_wait_with_b_still_going(self):
        _, seat, _ = self.case("api", True, "opus")
        line, = seat.wait_lines(1)
        self.assertIn(f"run {RUNS['api']} finished PASS", line)

    def test_b_merges_but_its_open_line_has_no_run_left_serving_it(self):
        _, seat, _ = self.case("web", False, "opus")
        line, = seat.wait_lines(1)
        self.assertIn(f"run {RUNS['web']} finished PASS", line)

    def test_a_missing_link_serves_no_line(self):
        _, seat, _ = self.case("web", True, "opus", linked=False)
        line, = seat.wait_lines(1)
        self.assertIn(f"run {RUNS['web']} finished PASS", line)

    def test_its_wait_on_a_recorded_ending_prints_it(self):
        home, seat, _ = self.case("web", True, "grok")
        done = home.ak("wait", RUNS["web"], env={"AGENTKIT_SESSION": seat.name})
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(f"run {RUNS['web']} finished PASS", done.err)
        self.assertEqual(seat.typed(), "")

    def test_live_after_the_merge_was_read_starts_no_turn_and_is_read_at_status(self):
        for model in ("opus", "grok"):
            with self.subTest(model=model):
                home, seat, ak = self.case("web", True, model)
                ak("run", "status", RUNS["web"])
                relative = f".agentkit/runs/{RUNS['web']}/run.json"
                state = json.loads((home.path / relative).read_text())
                state["live_at"] = time.time()
                home.write(relative, state)
                tick = home.tick()
                self.assertEqual(tick.code, 0, tick.out + tick.err)
                self.assertEqual(seat.typed(), "")
                self.assertIn(f"run {RUNS['web']} is live: ", ak("run", "status", RUNS["web"]))
                tick = home.tick()
                self.assertEqual(tick.code, 0, tick.out + tick.err)
                self.assertEqual(seat.typed(), "")


if __name__ == "__main__":
    unittest.main()
