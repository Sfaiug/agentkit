"""The daily git gc runs past the owner's processes ak cannot read, judging each by its command
line.

A login's `systemd --user`, its sshd sessions and `ssh-agent` hide their working directory and
descriptors even from their own user, while their command line stays readable.  Such a process
keeps a repository busy only when its command line names an absolute path inside it; anything
else does not hold the tick's daily `git gc` off.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, and this test fails against `/bin/false`.  The
whole file runs in one box (`rerun_boxed`): the tick must see the processes it started.
"""

from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import BOXED, Home, rerun_boxed

# PR_SET_DUMPABLE 0: its cwd and descriptors are unreadable to its own user, its argv is not.
HIDDEN = ("import ctypes, sys; ctypes.CDLL(None).prctl(4, 0, 0, 0, 0); "
          "print(flush=True); sys.stdin.read()")


@unittest.skipUnless(BOXED, "no bwrap able to box the test here")
class Unreadable(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        config = self.home.path / ".agentkit" / "config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        self.repo = self.home.path / "code" / "acme"
        self.repo.mkdir(parents=True)
        for argv in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "start"]):
            done = self.home.run("git", "-C", str(self.repo), *argv)
            self.assertEqual(done.code, 0, done.err)

    def hidden(self, *args):
        proc = subprocess.Popen([sys.executable, "-c", HIDDEN, *args], cwd=self.home.path,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.stdin.close)
        self.addCleanup(proc.stdout.close)
        proc.stdout.readline()
        with self.assertRaises(PermissionError):
            Path(f"/proc/{proc.pid}/cwd").readlink()

    def tick(self):
        done = self.home.ak("watch")
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def test_one_naming_no_repository_path_leaves_the_daily_gc_to_run(self):
        self.hidden("/usr/bin/ssh-agent")
        self.assertIn(f"git gc: {self.repo}", self.tick())

    def test_one_naming_a_path_inside_the_repository_keeps_it_busy(self):
        self.hidden(str(self.repo / "src" / "main.py"))
        self.assertNotIn(f"git gc: {self.repo}", self.tick())


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
