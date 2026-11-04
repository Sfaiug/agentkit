"""A failed merge's seat learns whether the live product runs it, from `deployed:`'s exit.

Black-box: AK_BIN in Home's tick box, with temporary projects, GitHub and seats. Both health
and deployment probes run twice inside the window; backdating the merges then ends it.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, boxable, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

HEALTH = "echo unhealthy; exit 1"
LIVE = "this merge is live and its health fails"
WAITING = "the live product does not run this merge yet"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class DeployedLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        config = cls.home.path / ".agentkit/config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        gh = GitHub(cls.home)
        cls.projects = {}
        for name, code in (("live", 0), ("waiting", 1), ("legacy", None)):
            # Output claims the opposite: only the exit decides whether the merge is live.
            deployed = (f'printf "%s\\n%s\\n" "$AK_MERGE_SHA" "$PWD" '
                        f'>>"$HOME/{name}-probes"; echo {WAITING if code == 0 else LIVE}; '
                        f'exit {code}') if code is not None else None
            front = f"deployed: {deployed}\n" if deployed else ""
            rig = Rig(cls.home, name, files={
                "AGENTS.md": f"---\nhealth: {HEALTH}\n{front}---\n"})
            sha = rig.head()
            gh.check(sha, "ci")
            seat = Seat(cls.home, name, cwd=rig.path)
            run = f"20261104-1200-{name}"
            now = time.time()
            path = cls.home.write(f".agentkit/runs/{run}/run.json", {
                "run_id": run, "state": "pass", "verdict": "PASS", "merged": True,
                "finished_at": now - 600, "started_at": now - 1200,
                "repo": str(rig.path), "pr": f"https://github.com/acme/{name}/pull/7",
                "merge_sha": sha, "health": {"command": HEALTH}, "launched_session": name})
            # The commit's declaration decides, even if the checkout now says otherwise.
            (rig.path / "AGENTS.md").write_text("---\ndeployed: exit 99\n---\n")
            cls.projects[name] = (rig, seat, path, deployed)
        cls.tick()
        cls.first = {name: json.loads(path.read_text())
                     for name, (_, _, path, _) in cls.projects.items()}
        cls.tick()
        for _, _, path, _ in cls.projects.values():
            state = json.loads(path.read_text())
            state["finished_at"] = time.time() - 4 * 3600
            path.write_text(json.dumps(state))
        cls.tick()

    @classmethod
    def tick(cls):
        done = cls.home.tick()
        assert done.code == 0, done.out + done.err

    def test_a_live_merge_with_failing_health_is_told_as_such(self):
        self.assertIn(LIVE, self.projects["live"][1].typed())

    def test_an_unreleased_merge_is_told_it_is_not_live_yet(self):
        self.assertIn(WAITING, self.projects["waiting"][1].typed())

    def test_without_the_line_the_seat_gets_todays_notice(self):
        run = "20261104-1200-legacy"
        self.assertEqual(self.projects["legacy"][1].lines(), [
            f"run {run} NOT LIVE (0 of 0): health: {HEALTH} failed on main after this merge. "
            "https://github.com/acme/legacy/pull/7; unhealthy. Fix the target. "
            f"Next: launch the fix the result names. Result: ~/.agentkit/runs/{run}/result.md"])

    def test_each_probe_uses_the_merge_sha_and_checkout_even_after_deployment_passes(self):
        for name in ("live", "waiting"):
            rig, _, path, command = self.projects[name]
            with self.subTest(project=name):
                self.assertEqual((self.home.path / f"{name}-probes").read_text().splitlines(),
                                 [rig.head(), str(rig.path)] * 2)
                self.assertEqual(json.loads(path.read_text())["deployed"], command)

    def test_the_first_deployment_pass_is_kept_without_marking_failing_health_live(self):
        for name, (_, _, path, _) in self.projects.items():
            state = json.loads(path.read_text())
            self.assertNotIn("live_at", state)
            if name == "live":
                self.assertIsInstance(self.first[name].get("deployed_at"), (int, float))
                self.assertEqual(state["deployed_at"], self.first[name]["deployed_at"])
            else:
                self.assertNotIn("deployed_at", state)


if __name__ == "__main__":
    unittest.main()
