"""A run that does not land is refused a done-when line only where bash reads that line as the
suite its target's commit declares, where their output goes aside.
Offline: a clone and its bare origin in a temporary folder, and the bash this machine has, which
prints a substitution it parsed from 5.2 on.
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
from agentkit import run, task

BARE = "sh suite.sh"
SUITE = f"{BARE} 2>&1 | tee suite.out"
LISTED = "git ls-files --error-unmatch tests/test_api.py"


class UnlandedSuiteLine(unittest.TestCase):
    def test_a_line_is_the_suite_as_bash_reads_both(self):
        for suite, line, same in (
                # the suite, where its output goes aside: with all of its plumbing, some or none
                (SUITE, BARE, True),
                (SUITE, f"{BARE} 2>&1|tee suite.out  # once", True),
                (SUITE, f"{BARE} 2>&1", True),
                (BARE, f"{BARE} >suite.out 2>&1", True),
                (f"test -f seed.txt && {SUITE}", f"test -f seed.txt&&{BARE}", True),
                ("sh check.sh 2>&1 --all", "sh check.sh --all", True),
                # however it is laid out, down into a substitution and a function
                (SUITE, "  sh \t suite.sh  # run all checks", True),
                (f"{BARE} $(printf  smoke)", f"{BARE} $(printf smoke)", True),
                ("launch() { sh suite.sh; }; launch", "launch () { sh suite.sh; }; launch", True),
                # and however a word nothing in which expands is quoted, in a bracket's commands
                # too
                ('sh "suite.sh" "smoke"', "sh suite.sh smoke", True),
                ("sh 'full  suite.sh'", 'sh "full  suite.sh"', True),
                ("sh 'full  suite.sh'", "sh full\\ \\ suite.sh", True),
                ('(cd app && sh "suite.sh" $(printf "smoke"))', f"( cd app&&{BARE} $(printf smoke) )",
                 True),
                # a part of the suite is a check of its own
                ("test -f seed.txt && sh suite.sh", "test -f seed.txt", False),
                ("cd app; sh suite.sh || cat suite.out", "cd app", False),
                (f"{SUITE} && sh later.sh", BARE, False),
                ("sh check.sh 2>&1 --all", "sh check.sh", False),
                # and what follows a pipe may be what runs it
                (f"{LISTED} | xargs python3", LISTED, False),
                (f"{LISTED} | tee >(xargs python3)", LISTED, False),
                (f"{BARE} '|' tee suite.out", BARE, False),
                # another word is another command: what a quote or a bracket holds is as written
                ("sh 'full  suite.sh'", "sh 'full suite.sh'", False),
                ('sh "$(echo "full  suite.sh")"', 'sh "$(echo "full suite.sh")"', False),
                (f"{BARE} ${{TAG:-a  b}}", f"{BARE} ${{TAG:-a b}}", False),
                (f"{BARE} $'it\\'s  on'", f"{BARE} $'it\\'s on'", False),
                (f"{BARE} tag#1", f"{BARE} tag", False),
                (f"{BARE} 2 >suite.out", f"{BARE} 2>suite.out", False),
                (f"diff <({BARE}) <(cat want)", f"diff <({BARE})<(cat want)", False),
                (f"{BARE} '*.sh'", f"{BARE} *.sh", False),
                (f"{BARE} $((1 + 2))", f"{BARE} $((1+2))", False),
                # so is a word bash knows by its unquoted spelling, a name it keeps as written,
                # and a line whose end `-c` leaves escaped
                (f"export MODE=$FLAGS; {BARE}", f'"export" MODE=$FLAGS; {BARE}', False),
                (f"time -p {BARE}", f'time "-p" {BARE}', False),
                (f'[[ $MODE =~ "a.c" ]] && {BARE}', f"[[ $MODE =~ a.c ]] && {BARE}", False),
                ("launch() { sh suite.sh; }; launch", '"launch" () { sh suite.sh; }; launch',
                 False),
                (f"for part in api web; do {BARE} $part; done",
                 f'for "part" in api web; do {BARE} $part; done', False),
                (f"{BARE} \\", BARE, False)):
            with self.subTest(suite=suite, line=line):
                self.assertIs(task.is_suite(line, suite), same)

    def test_bash_reads_a_line_and_runs_none_of_it(self):
        tmp = tempfile.TemporaryDirectory(prefix="unlanded-suite-")
        self.addCleanup(tmp.cleanup)
        ran = Path(tmp.name, "ran")
        startup = Path(tmp.name, "startup")
        startup.write_text(f"touch {ran}\n")
        with patch.dict(os.environ, {"BASH_ENV": str(startup), "SHELLOPTS": "verbose"}):
            self.assertEqual(task.printed(f"touch {ran} ;  sh  suite.sh # all"),
                             f"touch {ran}; sh suite.sh")
        self.assertFalse(ran.exists())
        # where bash prints none, the line stands as written
        self.assertIsNone(task.printed('sh "suite.sh'))
        with patch.object(task.subprocess, "run", side_effect=OSError("no bash")):
            self.assertIsNone(task.printed(BARE))
            self.assertTrue(task.is_suite("sh  'suite.sh' # all", SUITE))
            self.assertFalse(task.is_suite("sh 'full suite.sh'", "sh 'full  suite.sh'"))

    def test_the_suite_is_the_one_the_target_s_commit_declares(self):
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

        def declare(cwd, branch, suite, start=None):
            """`branch` declares `suite`: on origin too, unless it starts here, at `start`."""
            git(cwd, "checkout", "-q", "-B", branch, start or f"refs/remotes/origin/{branch}")
            (cwd / "AGENTS.md").write_text(f"---\ntests: {suite}\n---\n")
            git(cwd, "add", "AGENTS.md")
            git(cwd, "commit", "-q", "-m", f"{branch} declares {suite}")
            if not start:
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
        # origin's branch, however the task spells it and whatever else bears its short name;
        # main's suite is another, though release is what is checked out
        git(repo, "tag", "origin/release", "main")
        git(repo, "branch", "origin/release", "main")
        for target in ("release", "origin/release", "refs/heads/release",
                       "refs/remotes/origin/release"):
            with self.subTest(target=target):
                self.assertEqual(refusal(target), refused)
        self.assertIsNone(refusal("main"))
        # a run that lands runs it once, and a scratch run has no suite
        self.assertIsNone(refusal("release", landing=True))
        self.assertIsNone(refusal("release", where=None))
        # a branch origin has none of is the local one, never the checkout beside it
        declare(repo, "fix-api", SUITE, start="main")
        declare(repo, "fix-docs", "none", start="release")
        self.assertEqual(refusal("fix-api"), refused)
        self.assertIsNone(refusal("fix-docs"))
        git(repo, "checkout", "-q", "main")
        self.assertEqual(refusal("fix-api"), refused)
        self.assertIsNone(refusal("no-such-branch"))
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
