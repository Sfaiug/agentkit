"""A seat's rulebook gives its project's numbers and its project's rules from one commit of the
default branch, however a fetch moves that branch while they are read: never one revision's line
limit beside another's instructions.  Black-box: Claude's prompt hook as ak's adapter registers it,
fired for a seat that holds no rulebook yet, so it is told its rulebook whole
(tests/fixtures/hookdrive.py), with a git first on the program's PATH that moves the default branch
to the other of two revisions after each read naming AGENTS.md; this test fails against `/bin/false`.
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
# a fetch landing after every read of the rules: the branch swaps revisions each time
GIT = """#!/bin/sh
{git} "$@"; code=$?
case "$*" in *AGENTS.md*)
    at=$({git} -C {rig} rev-parse refs/remotes/origin/main)
    [ "$at" = {one} ] && to={two} || to={one}
    {git} -C {rig} update-ref refs/remotes/origin/main "$to";;
esac
exit $code
"""


def rules(limit):
    return {"AGENTS.md": f"---\ntests: true\nhealth: none\nusers: none\norchestrator_lines: {limit}\n"
                         f"---\nProject rule revision {limit}.\n"}


class OneCommit(unittest.TestCase):
    def test_a_fetch_between_reads_never_mixes_two_revisions_in_one_rulebook(self):
        with Home() as home:
            hooks = Hooks(home)
            rig = Rig(home, "acme", files=rules(17))
            one = rig.git("rev-parse", "HEAD")
            two = rig.commit(rules(29), "more lines", push=False)
            home.fake("git", GIT.format(git=shlex.quote(GIT_BIN), one=one, two=two,
                                        rig=shlex.quote(str(rig.path))))
            home.write(".agentkit/state/session-acme.json",
                       {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["opus"],
                        "cwd": str(rig.path), "repo": str(rig.path), "conversation": CONVERSATION,
                        "id_source": "launcher", "resumable": True})
            fired = hooks.fire("UserPromptSubmit", {"prompt": "go", "session_id": CONVERSATION},
                               seat="acme")
            self.assertEqual((fired.code, len(fired.said)), (0, 1), fired.out + fired.err)
            change = home.path / ".agentkit/state/change-acme.md"
            book = (change.read_text() if change.is_file() else
                    fired.said[0]["hookSpecificOutput"]["additionalContext"]).split(READ)[0]
            told = [n for n in (17, 29) if f"you build at most {n} added lines" in book
                    and f"Project rule revision {n}." in book]
            self.assertEqual(len(told), 1, [line for line in book.splitlines()
                                            if "at most" in line or "revision" in line])


if __name__ == "__main__":
    unittest.main()
