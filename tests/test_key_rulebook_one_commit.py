"""A seat's rulebook gives its project's numbers and its project's rules from one commit of the
default branch, however a fetch moves that branch while they are read: never one revision's line
limit beside another's instructions.  Black-box: Claude's prompt hook as ak's adapter registers it,
fired for a seat that holds no rulebook yet, so it is told its rulebook whole
(tests/fixtures/hookdrive.py), with a git first on the program's PATH that moves the default branch
to the other of two revisions after each command naming it; and with a pathspec setting
(GIT_GLOB_PATHSPECS, GIT_ICASE_PATHSPECS) inherited.  This test fails against `/bin/false`.
"""

import os
import shlex
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM, Home
from fixtures.gitrig import Rig
from fixtures.hookdrive import Hooks

GIT_BIN = shutil.which("git", path=os.pathsep.join(SYSTEM))
CONVERSATION = "7d3c1e2a-5b4f-4a6e-8c9d-0e1f2a3b4c5d"
READ = "\n\nOnce you have read all of the above"
# a fetch landing after every look at origin's branch, however the rules are read: it swaps
# revisions each time, so no two looks see the same one, and each swap is logged
GIT = """#!/bin/sh
{git} "$@"; code=$?
case "$*" in *origin/*)
    at=$({git} -C {rig} rev-parse refs/remotes/origin/main)
    [ "$at" = {one} ] && to={two} || to={one}
    {git} -C {rig} update-ref refs/remotes/origin/main "$to" && echo "$to" >> {moved};;
esac
exit $code
"""


def rules(limit):
    return {"AGENTS.md": f"---\ntests: true\nhealth: none\nusers: none\norchestrator_lines: {limit}\n"
                         f"---\nProject rule revision {limit}.\n"}


class OneCommit(unittest.TestCase):
    def rulebook(self, home, hooks, rig, env=None):
        """The whole rulebook the seat's first prompt hands it, without the line acknowledging it."""
        home.write(".agentkit/state/session-acme.json",
                   {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["opus"],
                    "cwd": str(rig.path), "repo": str(rig.path), "conversation": CONVERSATION,
                    "id_source": "launcher", "resumable": True})
        fired = hooks.fire("UserPromptSubmit", {"prompt": "go", "session_id": CONVERSATION},
                           seat="acme", env=env)
        self.assertEqual((fired.code, len(fired.said)), (0, 1), fired.out + fired.err)
        change = home.path / ".agentkit/state/change-acme.md"
        return (change.read_text() if change.is_file() else
                fired.said[0]["hookSpecificOutput"]["additionalContext"]).split(READ)[0]

    def test_a_fetch_between_reads_never_mixes_two_revisions_in_one_rulebook(self):
        with Home() as home:
            hooks = Hooks(home)
            rig = Rig(home, "acme", files=rules(17))
            one = rig.git("rev-parse", "HEAD")
            two = rig.commit(rules(29), "more lines", push=False)
            moved = home.root / "moved"
            home.fake("git", GIT.format(git=shlex.quote(GIT_BIN), one=one, two=two,
                                        rig=shlex.quote(str(rig.path)),
                                        moved=shlex.quote(str(moved))))
            book = self.rulebook(home, hooks, rig)
            self.assertTrue(moved.is_file(), "the branch never moved while the rules were read")
            told = [n for n in (17, 29) if f"you build at most {n} added lines" in book
                    and f"Project rule revision {n}." in book]
            self.assertEqual(len(told), 1, [line for line in book.splitlines()
                                            if "at most" in line or "revision" in line])

    def test_a_pathspec_setting_the_seat_inherits_never_loses_its_project_s_rules(self):
        for setting in ("GIT_GLOB_PATHSPECS", "GIT_ICASE_PATHSPECS"):
            with self.subTest(setting), Home() as home:
                hooks = Hooks(home)
                rig = Rig(home, "acme", files=rules(17))
                book = self.rulebook(home, hooks, rig, {setting: "1"})
                self.assertIn("you build at most 17 added lines", book)
                self.assertIn("Project rule revision 17.", book)

if __name__ == "__main__":
    unittest.main()
