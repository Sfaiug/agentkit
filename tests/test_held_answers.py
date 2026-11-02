"""In a pass an answer is held for a bounded time (`look.held`), so `orch.git_dirs` tells an open
screen what git said of a checkout up to that long ago; outside a pass nothing is held, so all else
that asks gets git's answer of the moment."""

import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import look, open_runs, orch


class Clock:
    now = 1000.0

    def monotonic(self):
        return self.now


class Held(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        patcher = patch.object(look, "time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.key, self.computed = self.id(), []

    def ask(self):
        return look.held(self.key, 60, lambda: self.computed.append(1) or len(self.computed))

    def test_two_passes_in_a_row_compute_once_and_every_seconds_later_again(self):
        with look.one_look():
            self.assertEqual(self.ask(), 1)
        self.clock.now += 59.9
        with look.one_look():
            self.assertEqual(self.ask(), 1)
        self.clock.now += 0.1
        with look.one_look():
            self.assertEqual(self.ask(), 2)

    def test_outside_a_pass_each_ask_computes_and_keeps_nothing(self):
        self.assertEqual(self.ask(), 1)
        self.assertEqual(self.ask(), 2)
        with look.one_look():
            self.assertEqual(self.ask(), 3)         # nothing kept from outside
        self.assertEqual(self.ask(), 4)             # nor anything of a pass's handed outside
        with look.one_look():
            self.assertEqual(self.ask(), 3)

    def test_a_pass_on_another_thread_gets_it_and_two_asking_at_once_compute_once(self):
        computing, answers = threading.Event(), []
        release = threading.Event()

        def slow():
            computing.set()
            release.wait(30)
            self.computed.append(1)
            return "acme"

        def asks():
            with look.one_look():
                answers.append(look.held(self.key, 60, slow))
        threads = [threading.Thread(target=asks) for _ in range(2)]
        threads[0].start()
        computing.wait(30)
        threads[1].start()
        threads[1].join(0.2)      # long enough to reach what holds it back, if anything does
        release.set()
        for thread in threads:
            thread.join()
        self.assertEqual((answers, self.computed), (["acme", "acme"], [1]))

    def test_what_was_held_past_its_time_is_let_go(self):
        with look.one_look():
            self.ask()
            self.clock.now += 60
            look.held(self.id() + " another", 60, lambda: None)
        self.assertNotIn(self.key, look._HELD)


class GitDirsHeld(Sandbox):
    def git(self, where, *args):
        env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
        subprocess.run(["git", "-c", "user.name=acme", "-c", "user.email=acme@example.com",
                        *args], cwd=where, env=env, check=True, capture_output=True)

    def test_a_repository_moved_and_relinked_reads_old_in_a_pass_until_its_time(self):
        clock = Clock()
        code, acme, moved = self.root / "code", self.root / "acme", self.root / "moved"
        code.mkdir()
        acme.mkdir()
        self.git(acme, "init", "-q")
        self.git(acme, "commit", "-q", "--allow-empty", "-m", "init")
        self.git(acme, "worktree", "add", "-q", "-b", "fix-api", str(code / "fix-api"))
        worktree = code / "fix-api"
        with patch.object(look, "time", clock):
            with look.one_look():
                self.assertEqual(orch.git_dirs(worktree), ((acme / ".git").resolve(), True))
            acme.rename(moved)
            self.git(moved, "worktree", "repair", str(worktree))
            new = ((moved / ".git").resolve(), True)
            self.assertEqual(orch.git_dirs(worktree), new)
            clock.now += open_runs.CEILING - 1
            with look.one_look():
                self.assertEqual(orch.git_dirs(worktree), ((acme / ".git").resolve(), True))
            clock.now += 1
            with look.one_look():
                self.assertEqual(orch.git_dirs(worktree), new)

    def test_two_spellings_of_one_checkout_ask_once(self):
        disk, linked, acme = self.root / "disk", self.root / "linked", self.root / "acme"
        disk.mkdir()
        linked.symlink_to(disk, target_is_directory=True)
        acme.mkdir()
        self.git(acme, "init", "-q")
        self.git(acme, "commit", "-q", "--allow-empty", "-m", "init")
        self.git(acme, "worktree", "add", "-q", "-b", "fix-api", str(linked / "fix-api"))
        with patch.object(orch, "git_in", wraps=orch.git_in) as asked, look.one_look():
            spelled = orch.git_dirs(linked / "fix-api")
            self.assertEqual(orch.git_dirs(disk / "fix-api"), spelled)
        self.assertEqual(asked.call_count, 1)

    def test_no_git_and_a_plain_git_directory_stay_outside_the_hold(self):
        clock, acme = Clock(), self.root / "acme"
        acme.mkdir()
        self.git(acme, "init", "-q")
        with patch.object(look, "time", clock), look.one_look():
            self.assertEqual(orch.git_dirs(acme), ((acme / ".git").resolve(), False))
            (acme / ".git").rename(self.root / "elsewhere")
            self.assertIsNone(orch.git_dirs(acme))


if __name__ == "__main__":
    unittest.main()
