"""Before each round's checks and review, overlapping target moves are rebased in.

Black-box through AK_BIN, akbin, gitrig, fakeadapter and fakegh. The executor pushes a
sibling to the bare origin during its turn; disjoint moves keep the review's old base.
After a rebase the reviewer reads the whole change, without mapping the old reviewed head.
"""

import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

TAIL = "".join(f"unchanged {n}\n" for n in range(12)) + "base tail\n"
BASE = "base start\n" + TAIL


def edit(text, command=None):
    return {"write": {"widget.txt": text, "retry.txt": "hello\n"}, "commit": "edit widget",
            **({"sh": command} if command else {}), "hand_in": [["done"]],
            "final": "## Summary\nEdited widget."}


class Round:
    elsewhere = conflict = fix = False

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.rig = rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\ntests: test -f retry.txt\n---\n# widgets\n",
            "widget.txt": BASE, "other.txt": "base\n"})
        cls.base = rig.head()
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        cls.fakes = fakes = fakeadapter.install(home, claude="work", codex="pass")
        writer = fakes["claude"]
        sibling = writer.dir / "sibling"
        cloned = home.run("git", "clone", "-q", str(rig.bare), str(sibling))
        assert cloned.code == 0, cloned.err
        # Both the sibling checkout and the bare origin are writable in this fake turn's box.
        writer.manifest.write_text(writer.manifest.read_text().replace(
            f"state = {json.dumps([str(writer.dir)])}",
            f"state = {json.dumps([str(writer.dir), str(rig.bare)])}"))
        path, text = ("other.txt", "sibling elsewhere\n") if cls.elsewhere else (
            "widget.txt", "sibling start\n" + TAIL if cls.conflict else
            BASE.replace("base tail", "sibling tail"))
        (sibling / path).write_text(text)
        git = f"git -C {shlex.quote(str(sibling))}"
        push = f"{git} add -A && {git} commit -qm sibling && {git} push -q origin HEAD:main"
        if cls.fix:
            writer.behave(edit("worker broken\n" + TAIL), edit("worker fixed\n" + TAIL, push))
            fakes["codex"].behave({"hand_in": [
                ["finding", "widget.txt:1", "broken widget", "the widget is broken", "--run",
                 "! grep -q broken widget.txt"], ["done"]], "final": "Found a defect."}, "pass")
        elif cls.conflict:
            resolved = shlex.quote("worker and sibling start\n" + TAIL)
            writer.behave(edit("worker start\n" + TAIL, push), {
                "sh": f"printf %s {resolved} > widget.txt && git add widget.txt && "
                      "GIT_EDITOR=true git rebase --continue",
                "hand_in": [["done"]], "final": "Resolved both sides."})
        else:
            writer.behave(edit("worker start\n" + TAIL, push))
        task = taskfile.write(home, rig.path, front={"rounds": 2 if cls.fix else 1})
        cls.done = home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.sibling = home.run("git", "-C", str(sibling), "rev-parse", "HEAD").out.strip()

    def test_the_run_passes_with_no_extra_task_round(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))
        expected = ["FAIL", "PASS"] if self.fix else ["PASS"]
        self.assertEqual(self.state["rounds"], len(expected))
        self.assertEqual([r["verdict"] for r in self.state["round_summaries"]], expected)
        self.assertTrue(all(r["done_when"] for r in self.state["round_summaries"]))
        if self.fix:
            self.assertEqual(self.state["round_summaries"][0]["finding_count"], 1)
        self.assertEqual(self.fakes["codex"].n, len(expected))
        self.assertNotEqual(self.sibling, self.base)

    def test_the_review_meets_overlapping_siblings_and_keeps_disjoint_ones_out(self):
        reviewed = self.state["round_summaries"][-1]["head_sha"]
        ancestor = self.home.run("git", "-C", str(self.rig.path), "merge-base",
                                 "--is-ancestor", self.sibling, reviewed)
        self.assertEqual(ancestor.code, 1 if self.elsewhere else 0, ancestor.err)
        if self.elsewhere:
            self.assertEqual(self.rig.git("rev-parse", f"{reviewed}^"), self.base)
        else:
            content = self.rig.git("show", f"{reviewed}:widget.txt")
            self.assertIn("sibling", content)
            self.assertIn("worker", content)

    def test_the_record_names_each_rebase_and_its_round(self):
        self.assertEqual(self.state.get("rebases", []), [] if self.elsewhere else [
            {"round": 2 if self.fix else 1, "onto": self.sibling}])


class SameFile(Round, unittest.TestCase):
    pass


class OtherFile(Round, unittest.TestCase):
    elsewhere = True


class SameLines(Round, unittest.TestCase):
    conflict = True

    def test_a_conflict_turn_preserves_both_sides_before_the_review(self):
        self.assertEqual([r["role"] for r in self.fakes["claude"].runs()], ["executor", "fixer"])
        prompt = (self.run_dir / "round-1/rebase-fixer/prompt.md").read_text()
        self.assertIn("## Resolve the rebase conflict", prompt)


class FixRound(Round, unittest.TestCase):
    fix = True

    def test_after_rebasing_a_fix_round_reviews_the_whole_change_against_the_new_base(self):
        prompt = (self.run_dir / "round-2/reviewer/prompt.md").read_text()
        self.assertIn("## Diff (", prompt)
        self.assertIn("+worker fixed", prompt)
        self.assertIn("diff --git a/retry.txt b/retry.txt", prompt)
        self.assertNotIn("## Fix delta (", prompt)
        self.assertNotIn("sibling tail", prompt)


if __name__ == "__main__":
    unittest.main()
