"""A follow-up proven to be caused by the change blocks, wherever its site is.

Black-box through AK_BIN: a fake reviewer hands in only a follow-up and done. A proof
passing on base and failing on the commit sends its site and the cause back to the fixer;
one failing on base too stays a follow-up and passes in round one.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

PROOF = "grep -qx ready retry.txt"
CAUSE = "its proof passes on base and fails on this commit, so this change caused it"


class CausedFollowUpBlocks(unittest.TestCase):
    def run_case(self, site, command):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={"retry.txt": "ready\n", "caller.txt": "uses retry.txt\n"})
        akconfig.write(home, ["opus", "astra"])
        work = {"write": {"retry.txt": "wrong\n", "feature.txt": "added\n"},
                "commit": "Add feature", "final": "## Summary\nAdded feature.", "hand_in": [["done"]]}
        fix = {"write": {"retry.txt": "ready\n"}, "commit": "Preserve retry setting",
               "final": "## Summary\nRestored retry setting.", "hand_in": [["done"]]}
        review = {"final": "Found one.", "hand_in": [
            ["follow-up", site, "retry setting is wrong", "breaks callers", "--run", command],
            ["done"]]}
        fakes = fakeadapter.install(home, claude=[work, fix], codex=[review, "pass"])
        task = taskfile.write(home, rig.path, "Add feature", done_when=("test -f feature.txt",))
        done = home.ak("run", str(task), "--no-merge", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        directory = taskfile.only_run(home)
        state = json.loads((directory / "run.json").read_text())
        self.assertEqual([(row["argv"][0], row["code"])
                          for row in fakes["codex"].runs()[0]["hand_ins"]],
                         [("follow-up", 0), ("done", 0)])
        return directory, state, fakes

    def test_a_caused_follow_up_blocks_on_changed_and_unchanged_lines(self):
        for site in ("retry.txt:1", "caller.txt:1"):
            with self.subTest(site=site):
                directory, state, fakes = self.run_case(site, PROOF)
                self.assertEqual([(row["verdict"], row["finding_count"])
                                  for row in state["round_summaries"]], [("FAIL", 1), ("PASS", 0)])
                self.assertEqual([row["role"] for row in fakes["claude"].runs()],
                                 ["executor", "fixer"])
                self.assertEqual(fakes["codex"].n, 2)
                prompt = (directory / "round-2/executor/prompt.md").read_text()
                self.assertIn(f"{site} - retry setting is wrong - breaks callers", prompt)
                self.assertIn(CAUSE, prompt)
                self.assertIn(f"$ {PROOF}", prompt)
                [finding] = json.loads((directory / "round-1/reviewer/findings.json").read_text())
                self.assertEqual((finding["kind"], finding["handed"]), ("finding", "follow-up"))
                self.assertNotEqual(finding["evidence"]["returncode"], 0)
                self.assertEqual(finding["evidence"]["base"]["returncode"], 0)
                self.assertEqual(state["followups"], [])
                self.assertEqual(state["followup_checks"], {})

    def test_a_proof_failing_on_base_too_stays_a_nonblocking_follow_up(self):
        directory, state, fakes = self.run_case("caller.txt:1", "false")
        self.assertEqual([(row["verdict"], row["finding_count"])
                          for row in state["round_summaries"]], [("PASS", 0)])
        self.assertEqual((fakes["claude"].n, fakes["codex"].n), (1, 1))
        [follow_up] = state["followups"]
        self.assertIn("caller.txt:1 - retry setting is wrong - breaks callers", follow_up)
        self.assertEqual(state["followup_checks"], {follow_up: "false"})
        self.assertEqual(json.loads((directory / "round-1/reviewer/findings.json").read_text()), [])


if __name__ == "__main__":
    unittest.main()
