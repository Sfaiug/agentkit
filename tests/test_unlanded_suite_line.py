"""A run that does not land is refused a done-when line only where that line is the suite its
target declares on origin now, word for word as the shell reads both.
Offline: a clone and its bare origin in a temporary folder.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import gitcall, run

BARE = "sh suite.sh"
SUITE = f"{BARE} 2>&1 | tee suite.out"
NESTED = "make test -j$(nproc | head -1)"


class UnlandedSuiteLine(unittest.TestCase):
    def test_a_line_is_the_suite_word_for_word(self):
        for suite, line, same in (
                # the suite, or the suite before its output plumbing, however either is spaced
                (SUITE, BARE, True),
                (SUITE, "  sh \t suite.sh  # run all checks", True),
                (SUITE, f"{BARE} 2>&1|tee suite.out  # once", True),
                (f"{BARE} > suite.out", f"{BARE} >suite.out", True),
                (f"{NESTED} 2>&1 | tee suite.out", NESTED, True),
                (f"test -f seed.txt && {SUITE}", f"test -f seed.txt&&{BARE}", True),
                # a part of the suite is a check of its own
                (SUITE, f"{BARE} 2>&1", False),
                ("test -f seed.txt && sh suite.sh", "test -f seed.txt", False),
                ("cd app; sh suite.sh || cat suite.out", "cd app", False),
                (f"{SUITE} && sh later.sh", BARE, False),
                # and so is another command: what a quote or a bracket holds is as written
                ("sh 'full  suite.sh'", "sh 'full suite.sh'", False),
                ('sh "$(echo "full  suite.sh")"', 'sh "$(echo "full suite.sh")"', False),
                (f"{BARE} ${{TAG:-a  b}}", f"{BARE} ${{TAG:-a b}}", False),
                (f"{BARE} $'it\\'s  on'", f"{BARE} $'it\\'s on'", False),
                (f"{BARE} tag#1", f"{BARE} tag", False),
                (f"{BARE} 2 >suite.out", f"{BARE} 2>suite.out", False),
                (f"diff <({BARE}) <(cat want)", f"diff <({BARE})<(cat want)", False),
                (f"{BARE} '|' tee suite.out", BARE, False)):
            with self.subTest(suite=suite, line=line):
                self.assertIs(gitcall.is_suite(line, suite), same)

    def test_the_suite_is_the_one_origin_declares_now(self):
        tmp = tempfile.TemporaryDirectory(prefix="unlanded-suite-")
        self.addCleanup(tmp.cleanup)
        origin, repo, other = (Path(tmp.name, name) for name in ("origin.git", "widgets", "other"))
        quiet = patch.dict(os.environ, {"HOME": tmp.name, "GIT_CONFIG_GLOBAL": os.devnull,
                                        "GIT_CONFIG_NOSYSTEM": "1"})
        quiet.start()
        self.addCleanup(quiet.stop)

        def git(cwd, *args):
            subprocess.run(["git", "-C", str(cwd), "-c", "user.name=fixture", "-c",
                            "user.email=fixture@localhost", *args], check=True, capture_output=True)

        def declare(cwd, branch, suite):
            git(cwd, "checkout", "-q", "-B", branch, f"origin/{branch}")
            (cwd / "AGENTS.md").write_text(f"---\ntests: {suite}\n---\n")
            git(cwd, "add", "AGENTS.md")
            git(cwd, "commit", "-q", "-m", f"{branch} declares {suite}")
            git(cwd, "push", "-q", "origin", branch)

        def refusal(target, where=repo, landing=False):
            return run.unlanded_suite_refusal(["test -f seed.txt", BARE], where, target,
                                              landing=landing)

        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        git(tmp.name, "clone", "-q", str(origin), str(repo))
        git(repo, "commit", "-q", "--allow-empty", "-m", "init")
        git(repo, "push", "-q", "origin", "HEAD:main", "HEAD:release")
        declare(repo, "main", "true")
        declare(repo, "release", SUITE)
        refused = (f"done-when line `{BARE}` is widgets's whole-suite `tests:` command, which ak "
                   "runs once, at landing, and --no-merge has no landing. Write a focused check "
                   "instead.")
        # the target's suite, however the task spells the target; main's is another
        for target in ("release", "origin/release", "refs/heads/release",
                       "refs/remotes/origin/release"):
            with self.subTest(target=target):
                self.assertEqual(refusal(target), refused)
        self.assertIsNone(refusal("main"))
        # a run that lands runs it once, and a scratch run has no suite
        self.assertIsNone(refusal("release", landing=True))
        self.assertIsNone(refusal("release", where=None))
        # origin moves on after the clone last fetched: main declares the suite, release drops it
        git(tmp.name, "clone", "-q", str(origin), str(other))
        declare(other, "main", SUITE)
        declare(other, "release", "none")
        self.assertEqual(refusal("main"), refused)
        self.assertIsNone(refusal("release"))
        # where origin does not answer, what the clone last fetched stands
        declare(other, "main", "true")
        with patch.object(run, "fetch", side_effect=run.Stopped("origin did not answer")):
            self.assertEqual(refusal("main"), refused)
        self.assertIsNone(refusal("main"))


if __name__ == "__main__":
    unittest.main()
