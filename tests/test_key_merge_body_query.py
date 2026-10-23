"""When GitHub cannot say what a merge's body would be, the work merges without the trailer.

A passing suite puts `Suite-Passed-Tree: <tree>` on the merge after the body GitHub would have
written, so ak first asks GitHub for that body: an explicit body replaces GitHub's own, and with
it whatever credit it carries.  If GitHub fails that question the trailer is left off, never
the merge: the trailer only lets CI skip a run, and work that passed review and its suite is
not held back for it.  The log says so with a warning naming the PR and GitHub's answer.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
against the bare origin of gitrig.py and the GitHub of fakegh.py, with scripted harnesses
from fakeadapter.py.
"""

import json
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import LOG, Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

SUITE = "grep -q hello retry.txt"
FAILED = "GraphQL: Something went wrong while executing your query."


def refuse_merge_body_text(home):
    """Have this Home's GitHub fail every question for a merge's default body, logging it as
    gh's other calls are, and answer the rest as before.  The field is GitHub's own name for
    that text, however the question is put."""
    github = (home.bin / "gh").read_text().split("\n", 1)[1]
    logged = LOG.format(python=shlex.quote(sys.executable),
                        log=shlex.quote(str(home.log("gh")))).split("\n", 1)[1]
    home.fake("gh", f'#!/bin/sh\ncase "$*" in\n  *viewerMergeBodyText*)\n    {logged}'
                    f"    echo {shlex.quote(FAILED)} >&2\n    exit 1 ;;\nesac\n{github}")


class MergeBodyQueryFails(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets",
                      files={"AGENTS.md": f"---\ntests: {SUITE}\n---\n# widgets\n"})
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        refuse_merge_body_text(cls.home)
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_run_still_ends_pass_and_merged(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        last = self.done.out.rstrip("\n").splitlines()[-1]
        self.assertTrue(last.endswith(f"PASS, merged -> {self.run_dir / 'result.md'}"), last)
        self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))
        self.assertIn("retry.txt", self.rig.files())

    def test_the_suite_passed_but_the_merge_carries_github_s_body_without_the_trailer(self):
        asked = [call for call in self.home.calls("gh") if "viewerMergeBodyText" in str(call)]
        self.assertTrue(asked, self.home.calls("gh"))
        checked = self.state["final_check"]
        self.assertEqual((checked["outcome"], checked["suite"]), ("passed", SUITE))
        self.assertEqual(self.rig.origin("log", "-1", "--format=%b", "main"), "* add retry.txt")

    def test_the_log_warns_naming_the_pr_and_what_github_said(self):
        log = (self.run_dir / "log.txt").read_text().splitlines()
        warned = [line for line in log if "WARN" in line and self.state["pr"] in line]
        self.assertEqual(len(warned), 1, log)
        self.assertIn(FAILED, warned[0])


if __name__ == "__main__":
    unittest.main()
