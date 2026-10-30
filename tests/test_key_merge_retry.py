"""After GitHub refuses a passed run's merge, `ak run merge <id>` finishes the delivery.

Work that passed review is never thrown away over one refused merge: the run ends PASS with
its PR left open, its worktree kept and result.md naming the command that finishes it, and
`ak run merge <id>` then merges that same PR at the very commit that was reviewed, with the
record saying so.  Asked again, a merged run says it is merged and merges nothing.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
against the bare origin of gitrig.py and the GitHub of fakegh.py, whose `pr merge` is refused
here while a flag file exists, with scripted harnesses from fakeadapter.py.
"""

import json
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# GitHub's answer to a merge it will not do yet, logged as fakegh logs every call.
REFUSING = """#!/bin/sh
if [ -e {flag} ] && [ "$1 $2" = "pr merge" ]; then
  {python} -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@" >>{log}
  echo 'GraphQL: Pull Request is not mergeable (mergePullRequest)' >&2
  exit 1
fi
"""


def merges(home):
    return [call for call in home.calls("gh") if call[:2] == ["pr", "merge"]]


class MergeRetry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.rig = Rig(home, "widgets")
        cls.gh = GitHub(home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        flag = home.root / "merge-refused"
        flag.write_text("")
        delegate = (home.bin / "gh").read_text().split("\n", 1)[1]
        home.fake("gh", REFUSING.format(flag=shlex.quote(str(flag)),
                                        python=shlex.quote(sys.executable),
                                        log=shlex.quote(str(home.log("gh")))) + delegate)
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex="pass")
        task = taskfile.write(home, cls.rig.path, "Add retry file")
        cls.first = home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(home)
        cls.failed = cls.record()
        cls.failed_result = cls.result()
        cls.pr_after_failure = cls.gh.pr(1)["state"] if cls.gh.prs() else None
        cls.kept = Path(cls.failed["worktree"]).is_dir()

        flag.unlink()
        cls.retry = home.ak("run", "merge", cls.run_dir.name, timeout=300)
        cls.merged = cls.record()
        cls.merged_result = cls.result()

        cls.merges_before = len(merges(home))
        cls.again = home.ak("run", "merge", cls.run_dir.name, timeout=300)
        cls.merges_after = len(merges(home))

    @classmethod
    def record(cls):
        return json.loads((cls.run_dir / "run.json").read_text())

    @classmethod
    def result(cls):
        return (cls.run_dir / "result.md").read_text().splitlines()

    def test_a_refused_merge_ends_the_run_pass_not_merged_with_its_pr_left_open(self):
        self.assertEqual(self.first.code, 1, self.first.out + self.first.err)
        self.assertEqual({key: self.failed.get(key) for key in (
            "state", "verdict", "merged", "merge_failed", "pr")}, {
            "state": "pass", "verdict": "PASS", "merged": False, "merge_failed": True,
            "pr": "https://github.com/acme/widgets/pull/1"})
        self.assertIn("not mergeable", self.failed["merge_note"])
        self.assertEqual(self.pr_after_failure, "OPEN")
        self.assertTrue(self.kept, "the worktree the retry delivers from was removed")
        last = self.first.out.rstrip("\n").splitlines()[-1]
        self.assertIn("PASS, not merged: ", last)
        self.assertTrue(last.endswith(f" -> {self.run_dir / 'result.md'}"), last)

    def test_result_md_says_why_and_names_the_command_that_finishes_the_delivery(self):
        notice, lines = self.failed_result[:4], self.failed_result[4:]
        self.assertRegex(notice[2], rf" NOT MERGED \(1 of 3\): .+ Next: launch the fix the result names, "
                                    rf"`ak run merge {self.run_dir.name}`\. Result: ")
        self.assertTrue(lines[0].startswith("# PASS, not merged: "), lines[0])
        self.assertIn("not mergeable", lines[0])
        self.assertTrue(lines[0].endswith(" — Add retry file"), lines[0])
        for line in ("VERDICT: PASS", f"pr: {self.failed['pr']}", "merged: no",
                     f"retry delivery: ak run merge {self.run_dir.name}"):
            self.assertIn(line, lines)

    def test_ak_run_merge_merges_the_same_pr_at_the_reviewed_commit(self):
        self.assertEqual(self.retry.code, 0, self.retry.out + self.retry.err)
        last = self.retry.out.rstrip("\n").splitlines()[-1]
        self.assertTrue(last.endswith(f"PASS, merged -> {self.run_dir / 'result.md'}"), last)
        self.assertEqual(len(self.gh.prs()), 1, self.gh.prs())
        reviewed = self.failed["delivery_sha"]
        self.assertEqual(reviewed, self.failed["review"]["head_sha"])
        merge = self.gh.pr(1)["merge"]
        self.assertEqual({key: merge[key] for key in ("method", "head", "match", "deleted")},
                         {"method": "squash", "head": reviewed, "match": reviewed,
                          "deleted": True})
        self.assertEqual(self.rig.branches(), ["main"])
        self.assertEqual(self.rig.head(), merge["commit"])
        self.assertIn("retry.txt", self.rig.files())

    def test_the_record_then_says_merged_and_the_worktree_is_gone(self):
        self.assertEqual({key: self.merged.get(key) for key in (
            "state", "verdict", "merged", "merge_failed", "merge_note", "pr", "delivery_sha")}, {
            "state": "pass", "verdict": "PASS", "merged": True, "merge_failed": False,
            "merge_note": None, "pr": self.failed["pr"],
            "delivery_sha": self.failed["delivery_sha"]})
        lines = self.merged_result
        self.assertEqual(lines[0], "# PASS, merged — Add retry file")
        for line in ("VERDICT: PASS", f"pr: {self.failed['pr']}", "merged: yes"):
            self.assertIn(line, lines)
        self.assertFalse([line for line in lines if line.startswith("retry delivery:")], lines)
        self.assertFalse(Path(self.merged["worktree"]).exists())

    def test_a_merged_run_merged_again_says_merged_and_merges_nothing(self):
        self.assertEqual(self.again.code, 0, self.again.out + self.again.err)
        self.assertTrue(self.again.out.rstrip("\n").endswith("PASS, merged"), self.again.out)
        self.assertEqual(self.merges_after, self.merges_before)
        self.assertEqual(self.record()["merged"], True)


if __name__ == "__main__":
    unittest.main()
