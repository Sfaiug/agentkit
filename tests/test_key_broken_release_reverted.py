"""A broken live release gets one revert through the line, unless its diff changes schema.

Black-box through AK_BIN, with health_pass's Home and seats. No harness is logged in:
the refused launch leaves the revert's task and record. Backdate deployment, never wait.
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

HEALTH = 'test -e "$HOME/healthy"'
DEPLOYED = 'test -e "$HOME/released"'


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class BrokenReleaseReverted(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        config = self.home.path / ".agentkit/config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        self.gh = GitHub(self.home)
        self.home.write("released", "")

    def project(self, *, deployed=True):
        front = f"deployed: {DEPLOYED}\n" if deployed else ""
        self.rig = Rig(self.home, "app", files={
            "AGENTS.md": f"---\ntests: true\nhealth: {HEALTH}\n{front}---\n"})
        self.seat = Seat(self.home, "acme", cwd=self.rig.path)

    def merge(self, name="release", files=None, *, merge=False):
        files = files or {"api.txt": name + "\n"}
        if merge:
            self.rig.branch(name, files)
            self.rig.git("merge", "--no-ff", "-qm", name, name)
            sha = self.rig.head(remote=False)
        else:
            sha = self.rig.commit(files)
        now = time.time()
        path = self.home.write(f".agentkit/runs/{name}/run.json", {
            "run_id": name, "state": "pass", "verdict": "PASS", "merged": True,
            "finished_at": now - 600, "started_at": now - 1200, "target": "main",
            "repo": str(self.rig.path), "pr": "https://github.com/acme/app/pull/7",
            "merge_sha": sha, "health": {"command": HEALTH},
            "launched_session": "acme", "reported": True,
            "handed_back": now - 600})
        return path, sha

    def tick(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def age(self, *paths):
        for path in paths:
            state = json.loads(path.read_text())
            state["deployed_at"] -= 301
            path.write_text(json.dumps(state))

    def reverts(self):
        return [path.parent for path in (self.home.path / ".agentkit/runs").glob("*/run.json")
                if json.loads(path.read_text()).get("followup")]

    def test_three_failures_after_the_floor_open_one_owned_revert_of_either_merge_kind(self):
        self.project()
        for merged in (False, True):
            with self.subTest(merge=merged):
                path, sha = self.merge(f"release-{merged}", merge=merged)
                before = len(self.reverts())
                self.tick()
                self.tick()
                self.assertEqual(len(self.reverts()), before)  # deployment's five minutes
                self.age(path)
                self.tick()
                reverts = self.reverts()
                self.assertEqual(len(reverts), before + 1)
                directory = next(p for p in reverts if json.loads(
                    (p / "run.json").read_text())["followup"]["run"] == path.parent.name)
                record = json.loads((directory / "run.json").read_text())
                self.assertEqual(record["launched_session"], "acme")
                command = f"git revert {'-m 1 ' if merged else ''}{sha}"
                task = (directory / "task.md").read_text()
                self.assertIn(command, task)
                self.assertIn("target: main", task)
                self.assertTrue(any("NOT LIVE" in line and directory.name in line
                                    for line in self.seat.lines()), self.seat.lines())
                self.assertEqual(self.rig.head(remote=False), sha)  # launch never reverts here
                self.tick()
                self.assertEqual(len(self.reverts()), before + 1)
                check = task.partition("```bash\n")[2].partition("```")[0]
                self.assertNotEqual(self.home.run("bash", "-c", check, cwd=self.rig.path).code, 0)
                self.rig.git("revert", "--no-edit", *(["-m", "1"] if merged else []), sha)
                self.assertEqual(self.home.run("bash", "-c", check, cwd=self.rig.path).code, 0)

    def test_schema_changes_are_named_instead_of_reverted(self):
        self.project()
        for name in ("db/migrations/001.py", "alembic/versions/002.py", "schema.sql"):
            with self.subTest(path=name):
                path, _ = self.merge(name.replace("/", "-"), {name: "schema change\n"})
                self.tick()
                self.age(path)
                self.tick()
                self.assertEqual(self.reverts(), [])  # two failures are still too few
                self.tick()
                self.assertEqual(self.reverts(), [])
                self.assertTrue(any("NOT LIVE" in line and "schema" in line
                                    for line in self.seat.lines()), self.seat.lines())

    def test_a_project_without_deployed_never_gets_a_revert(self):
        self.project(deployed=False)
        self.merge()
        for _ in range(3):
            self.tick()
        self.assertEqual(self.reverts(), [])

    def test_a_projects_own_rollback_prevents_a_revert(self):
        self.project()
        path, _ = self.merge()
        self.tick()
        self.age(path)
        self.tick()
        (self.home.path / "released").unlink()
        self.tick()
        self.assertEqual(self.reverts(), [])

    def test_health_is_followed_after_a_pass_and_only_the_newest_live_merge_is_reverted(self):
        self.project()
        first, _ = self.merge("first")
        self.home.write("healthy", "")
        self.tick()
        self.age(first)
        second, sha = self.merge("second")
        self.tick()
        self.age(second)
        (self.home.path / "healthy").unlink()
        for _ in range(2):
            self.tick()
        self.assertEqual(self.reverts(), [])
        self.home.write("healthy", "")
        self.tick()
        (self.home.path / "healthy").unlink()
        for _ in range(2):
            self.tick()
        self.assertEqual(self.reverts(), [])
        self.tick()
        self.assertEqual(len(self.reverts()), 1)
        self.assertIn(f"git revert {sha}", (self.reverts()[0] / "task.md").read_text())


if __name__ == "__main__":
    unittest.main()
