"""A finding the fixer disputes is dropped unless the next reviewer hands it in again.

A fixer handed a blocking finding may answer it with `ak hand-in dispute` and a passing proof
instead of changing code; it may not file findings of its own, and no other turn may dispute.
ak gives the next reviewer the dispute and ak's own run of its proof beside the finding and
does not re-prove the disputed finding itself: a reviewer who hands it in again upholds it and
the round fails, and one who does not drops it into result.md's Disputes, where a person reads
what was let go and why.  Black-box: the program `AK_BIN` names runs `ak run --no-merge` from
outside through tests/fixtures/akbin.py, on a project from gitrig.py with scripted harnesses
from fakeadapter.py; the reviewer's finding is fakeadapter's `fail`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

FINDING = "retry.txt:1 - fixture defect - the fixture says so"
# What a fixer tries, in order: a finding of its own, a dispute of a site it was not handed, a
# dispute whose proof fails, then the dispute that holds.
FIXER = {"final": "Disputed.", "hand_in": [
    ["finding", "retry.txt:1", "another defect", "it matters", "--run", "false"],
    ["dispute", "retry.txt:2", "it is right", "--run", "true"],
    ["dispute", "retry.txt:1", "it is right", "--run", "false"],
    ["dispute", "retry.txt:1", "it is right", "--run", "true"], ["done"]]}
REVIEWER_DISPUTES = {"final": "Looks right.", "hand_in": [
    ["dispute", "retry.txt:1", "a reviewer's dispute", "--run", "true"], ["done"]]}


def start(cls, reviews, rounds=None):
    cls.home = Home()
    cls.addClassCleanup(cls.home.close)
    cls.rig = Rig(cls.home, "widgets")
    akconfig.write(cls.home, ["opus", "astra"])
    cls.fakes = fakeadapter.install(cls.home, claude=["work", FIXER], codex=reviews)
    task = taskfile.write(cls.home, cls.rig.path, "Add retry file",
                          front={"rounds": rounds} if rounds else None)
    cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
    cls.run_dir = taskfile.only_run(cls.home)
    cls.state = json.loads((cls.run_dir / "run.json").read_text())
    cls.result = (cls.run_dir / "result.md").read_text()


def section(text, heading):
    """The lines under `heading` up to the next heading of its level."""
    lines = text.splitlines()
    assert heading in lines, f"no {heading!r} in:\n{text}"
    rest = lines[lines.index(heading) + 1:]
    return rest[:next((i for i, line in enumerate(rest) if line.startswith("## ")), len(rest))]


class DisputeDropped(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start(cls, ["fail", REVIEWER_DISPUTES])

    def codes(self, harness, call):
        run = self.fakes[harness].runs()[call - 1]
        return [(row["argv"][0], row["code"]) for row in run["hand_ins"]]

    def test_only_a_fixer_disputes_and_only_a_handed_finding_with_a_passing_proof(self):
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()],
                         ["executor", "fixer"])
        self.assertEqual(self.codes("claude", 2), [
            ("finding", 2), ("dispute", 2), ("dispute", 2), ("dispute", 0), ("done", 0)])
        self.assertEqual(self.codes("codex", 2), [("dispute", 2), ("done", 0)])
        # A refused hand-in leaves nothing in the turn's record.
        record = self.run_dir / "round-2/executor/hand-in.jsonl"
        rows = [json.loads(line) for line in record.read_text().splitlines()]
        self.assertEqual([row["kind"] for row in rows], ["turn", "dispute", "done"])
        self.assertEqual((rows[1]["path"], rows[1]["line"], rows[1]["why"]),
                         ("retry.txt", 1, "it is right"))

    def test_the_next_reviewer_reads_the_dispute_and_ak_s_own_proof_beside_the_finding(self):
        prompt = Path(self.fakes["codex"].runs()[1]["argv"][3]).read_text()
        disputes = section(prompt, "## Disputes")
        self.assertEqual(disputes[0], f"- {FINDING}")
        told = "\n".join(disputes[disputes.index("  Dispute: it is right"):])
        head = self.rig.head("ak/add-retry-file", remote=False)
        self.assertIn(f"  $ true\n  Commit {head}:\n  [exit 0]", told)
        self.assertTrue((self.run_dir / "round-2/dispute-1.log").is_file())
        # Disputed, it is the reviewer's to weigh: ak lists it and does not re-prove it.
        left = "\n".join(section(prompt, "## Earlier findings left to you"))
        self.assertIn("retry.txt:1 - fixture defect", left)
        self.assertIn("disputed", left)

    def test_a_finding_not_handed_in_again_is_dropped_into_disputes_and_the_run_passes(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["FAIL", "PASS"])
        lines = self.result.splitlines()
        self.assertEqual(lines[0], "# PASS, not merged: --no-merge — Add retry file")
        self.assertIn("rounds: 2 of 3", lines)
        disputes = section(self.result, "## Disputes")
        self.assertEqual(disputes[:2], ["", f"- Dropped: {FINDING}"])
        self.assertIn("  Dispute: it is right", disputes)
        self.assertNotIn("## Findings", lines)


class DisputeUpheld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start(cls, ["fail", "fail"], rounds=2)

    def test_a_finding_handed_in_again_blocks_and_nothing_is_dropped(self):
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()],
                         ["executor", "fixer"])
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"]), ("fail", "FAIL"))
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["FAIL", "FAIL"])
        lines = self.result.splitlines()
        self.assertEqual(lines[0], "# FAIL — Add retry file")
        self.assertIn("rounds: 2 of 2", lines)
        self.assertIn(f"- {FINDING}", section(self.result, "## Findings"))
        self.assertNotIn("## Disputes", lines)
        self.assertNotIn("Dropped:", self.result)


if __name__ == "__main__":
    unittest.main()
