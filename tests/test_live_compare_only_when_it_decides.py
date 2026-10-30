"""A red tip is compared with the running install exactly when the comparison can decide.

Offline: origin is a throwaway bare repository, ~/agentkit its clone under a temporary HOME,
behind it.  Only the suite body is fake -- it writes `exit`, `output` and `failed` the way
tests/live.sh does -- and so is the seat a red is handed to.
"""

from contextlib import ExitStack
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, update, watch


def git(where, *args):
    return subprocess.run(["git", "-C", str(where), *args], check=True, capture_output=True,
                          text=True, timeout=60).stdout.strip()


class LiveCompareOnlyWhenItDecides(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-live-compare-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}))
        stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        self.origin, self.seed, self.clone = (self.root / "origin.git", self.root / "seed",
                                              self.root / "agentkit")
        stack.enter_context(patch.object(config, "REPO", self.clone))
        stack.enter_context(patch.object(orch, "start_in_slice", side_effect=self.start))
        stack.enter_context(patch.object(watch, "after_merge_deliver", side_effect=self.deliver))
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)],
                       check=True, timeout=60)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.seed)],
                       check=True, capture_output=True, timeout=60)
        git(self.seed, "symbolic-ref", "HEAD", "refs/heads/main")
        (self.seed / "tests").mkdir()
        (self.seed / "tests/live.sh").write_text("exit 1\n")   # never run: the suite is faked
        (self.seed / "install.sh").write_text("#!/bin/sh\n")
        (self.seed / "install.sh").chmod(0o755)
        self.first = self.merge("first")
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.clone)],
                       check=True, capture_output=True, timeout=60)
        self.now, self.suites, self.started, self.handed = int(time.time()), {}, [], []

    def merge(self, text):
        (self.seed / "notes").write_text(text + "\n")
        git(self.seed, "add", "-A")
        git(self.seed, "commit", "-q", "-m", text)
        git(self.seed, "push", "-q", "origin", "main")
        return git(self.seed, "rev-parse", "HEAD")

    def start(self, argv, *_args, **_kw):
        """The suite body: that commit's results, ended a second after the check began."""
        check, commit = Path(argv[3]), argv[5]
        self.started.append(commit)
        suite = self.suites[commit]
        if suite is None:       # capped or stopped: it never wrote an exit code
            (check / "output.tmp").write_text("live: check 3 waiting\n")
            return
        code, said = 1, "".join(f"FAIL  {label}: refused\n" for label in suite)
        (check / "failed").write_text("".join(f"{label}\n" for label in suite))
        (check / "output").write_text(said)
        (check / "exit").write_text(f"{code}\n")
        ended = int(check.name.rsplit("-", 1)[1]) + 1
        os.utime(check / "exit", (ended, ended))

    def deliver(self, _run_dir, _state, _key, line, _log, **_kw):
        self.handed.append(line)
        return True

    def tick(self, after=1):
        self.now += after
        update.go_live(lambda _: None, now=self.now)

    def head(self):
        return git(self.clone, "rev-parse", "HEAD")

    def test_a_failed_fetch_decides_on_the_origin_main_fetched_last(self):
        older = self.merge("older")
        self.suites.update({older: ["3"], self.first: ["3"]})
        self.tick()
        tip = self.merge("tip")
        self.suites[tip] = ["3"]
        self.tick()
        self.assertEqual((self.started, self.handed), ([older, tip], []))
        self.origin.rename(self.root / "away.git")
        self.tick()     # the second red waits for HEAD's check, which waits for a fetch
        self.assertEqual((self.started, self.handed, self.head()), ([older, tip], [], self.first))
        (self.root / "away.git").rename(self.origin)
        self.tick()
        self.assertEqual(self.started, [older, tip, self.first])
        self.tick()
        self.assertEqual(self.head(), tip)
        self.assertEqual(len(self.handed), 1)
        self.assertIn("standing faults", self.handed[0])

    def held_without_a_head_check(self, suite):
        tip = self.merge("tip")
        self.suites[tip] = suite
        self.tick()
        self.tick()
        self.tick(watch.RETRY_BACKOFF[0] - 2)
        self.assertEqual((self.started, self.handed), ([tip], []))
        self.tick(2)
        self.assertEqual(self.started, [tip, tip])
        self.tick()
        self.assertEqual((self.started, self.head()), ([tip, tip], self.first))
        self.assertEqual(len(self.handed), 1)
        self.assertIn("Fix main", self.handed[0])

    def test_a_red_with_no_exit_code_is_held_without_a_head_check(self):
        self.held_without_a_head_check(None)

    def test_a_red_with_no_label_is_held_without_a_head_check(self):
        self.held_without_a_head_check([])


if __name__ == "__main__":
    unittest.main()
