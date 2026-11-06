"""Each role's line gate accepts `no limit`, in config.toml or project front matter.

Black-box: AK_BIN runs through the same isolated fixtures as test_key_lines_are_settings.py.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


class NoLimit(unittest.TestCase):
    def prepare(self, key, value="no limit", *, front=False):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus", "astra"], settings={} if front else {key: value})
        files = {"AGENTS.md": f"---\ntests: true\nhealth: none\n{key}: {value}\n---\nA project.\n"} if front else {}
        self.rig = Rig(self.home, "widgets", files=files)
        self.rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")

    def reviews(self):
        return sum(turn["role"] == "reviewer" for fake in self.fakes.values() for turn in fake.runs())

    def test_a_two_thousand_line_task_reaches_review(self):
        for front in (False, True):
            with self.subTest(front=front):
                self.prepare("executor_lines", front=front)
                self.fakes["claude"].behave({
                    "write": {"retry.txt": "".join(f"row {k:04d}\n" for k in range(2000))},
                    "commit": "the change", "final": "## Summary\nwrote it",
                    "hand_in": [["done"]]})
                task = taskfile.write(self.home, self.rig.path, "Rewrite the table")
                done = self.home.ak("run", str(task), "--no-merge", timeout=300)
                self.assertEqual(done.code, 0, done.out + done.err)
                state = json.loads((taskfile.only_run(self.home) / "run.json").read_text())
                self.assertEqual((state["verdict"], self.reviews()), ("PASS", 1))

    def test_a_seat_s_own_five_hundred_line_pull_request_is_reviewed(self):
        for front in (False, True):
            with self.subTest(front=front):
                self.prepare("orchestrator_lines", front=front)
                gh = GitHub(self.home)
                Seat(self.home, "acme", model="opus", cwd=self.rig.path, alive=False, planned=True)
                self.rig.branch("rewrite-table", {"contrib.txt": "row\n" * 500})
                url = gh.open_pr(self.rig, "rewrite-table", title="Rewrite the table")
                done = self.home.ak("run", "--review-pr", url, "--no-merge", cwd=self.rig.path,
                                    env={"AGENTKIT_SESSION": "acme"}, timeout=300)
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertEqual(self.reviews(), 1)

    def test_other_text_is_refused_naming_the_accepted_values(self):
        for front in (False, True):
            for key, floor in (("executor_lines", 0), ("orchestrator_lines", 0)):
                with self.subTest(front=front, key=key):
                    self.prepare(key, "lots", front=front)
                    task = taskfile.write(self.home, self.rig.path)
                    done = self.home.ak("run", str(task), "--no-merge", timeout=60)
                    self.assertEqual(done.code, 2, done.out + done.err)
                    self.assertIn(f'{key} must be a whole number of at least {floor} or "no limit"',
                                  done.err)
                    self.assertEqual(taskfile.runs(self.home), [])


if __name__ == "__main__":
    unittest.main()
