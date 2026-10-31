"""The answer key's runner keeps the program it runs away from the caller's world.

A test of the answer key runs a whole ak program, which reaches for tmux, GitHub and the owner's
units on its own; tests/fixtures/akbin.py is all that stands between it and the real ones.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home, _strays, boxable
from fixtures.clock import Clock


class Exec:
    """A /proc entry whose reads come in turn, as from a process in the middle of an exec, the
    last of each for good."""

    def __init__(self, pid, **reads):
        self.name, self.reads = str(pid), reads

    def __truediv__(self, field):
        reads = self.reads[field]
        return SimpleNamespace(read_bytes=lambda: reads.pop(0) if len(reads) > 1 else reads[0])


class Runner(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def test_the_program_sees_none_of_the_callers_environment(self):
        planted = {"AGENTKIT_SESSION": "acme", "AK_RUN_ID": "run-1", "TMUX": "/tmp/x,1,0",
                   "TMUX_PANE": "%1", "CLAUDE_CONFIG_DIR": "/tmp/claude"}
        with patch.dict(os.environ, planted):
            done = self.home.run("env")
        names = {line.partition("=")[0] for line in done.out.splitlines()}
        self.assertFalse(names & set(planted), done.out)
        self.assertIn(f"HOME={self.home.path}", done.out.splitlines())

    def test_a_host_tool_is_logged_and_refused(self):
        done = self.home.run("gh", "pr", "merge", "1")
        self.assertEqual(done.code, 1)
        self.assertEqual(self.home.calls("gh"), [["pr", "merge", "1"]])

    def test_a_terminal_on_stdin_carries_what_was_typed(self):
        done = self.home.run("sh", "-c", 'test -t 0 && read -r answer && echo "$answer"',
                             input="yes\n", tty=True, timeout=30)
        self.assertEqual((done.code, done.out), (0, "yes\n"))

    def test_a_hang_fails_and_leaves_nothing_running(self):
        with self.assertRaisesRegex(AssertionError, "still running after 1 s: sleep 60"):
            self.home.run(Path("sleep"), "60", timeout=1)     # an argument may be a Path

    @unittest.skipUnless(Path("/proc/self/environ").exists(), "no /proc to find strays in")
    def test_a_hang_fails_while_a_detached_process_still_holds_its_output(self):
        with self.assertRaisesRegex(AssertionError, "still running after 1 s"):
            self.home.run("sh", "-c", "setsid sleep 60 & sleep 60", timeout=1)
        self.assertTrue(_strays(self.home.path))

    @unittest.skipUnless(Path("/proc/self/environ").exists(), "no /proc to find strays in")
    def test_a_process_the_program_detached_ends_with_the_home(self):
        done = self.home.run("sh", "-c", "setsid sleep 60 </dev/null >/dev/null 2>&1 & echo $!")
        pid = int(done.out)
        self.home.close()
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertFalse(self.home.root.exists())

    def test_a_process_caught_in_an_exec_is_found_once_the_exec_sets_its_environment(self):
        fields = [b"1"] * 50
        fields[23:25] = [b"0", b"0"]      # its environment being walked, its code not placed yet
        execing = b"7 (sh) " + b" ".join(fields)
        entries = [Exec(6, environ=[b""], stat=[execing]),        # stuck there for good
                   Exec(7, environ=[b"", b"", f"HOME={self.home.path}\0".encode()],
                        stat=[execing])]
        slept = []      # each sleep a second, so the stuck exec is given up after STUCK of them
        clock = Clock(slept.append)
        clock.monotonic = lambda: len(slept)
        with patch.object(Path, "glob", return_value=entries), patch("fixtures.akbin.time", clock):
            self.assertEqual(_strays(self.home.path), [7])

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_a_tick_waits_out_what_it_detached_however_long_it_runs(self):
        # as a run the tick resumes goes on in its box, past a minute on a loaded host
        slow = self.home.path / "slow-ak"
        slow.write_text("#!/bin/sh\nsetsid sh -c 'sleep 65; touch \"$HOME/ended\"' "
                        "</dev/null >/dev/null 2>&1 &\n")
        slow.chmod(0o755)
        with patch("fixtures.akbin.AK", str(slow)):
            done = self.home.tick()
        self.assertEqual(done.code, 0, done.err)
        self.assertTrue((self.home.path / "ended").exists())

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_tmux_is_real_and_only_this_homes_own(self):
        own = self.home.tmux_dir / f"tmux-{os.getuid()}" / SOCKET
        # links inside the socket directory that lead out of it
        (self.home.tmux_dir / "out").symlink_to("/tmp", target_is_directory=True)
        (self.home.tmux_dir / "linked.sock").symlink_to("/tmp/elsewhere")
        for flags in (["-S", "/tmp/elsewhere"], ["-2S/tmp/elsewhere"], ["-2uS", "/tmp/elsewhere"],
                      ["-2f", "/dev/null", "-S", "/tmp/elsewhere"], ["-L", "../../elsewhere"],
                      ["-uL../../elsewhere"], ["-S", f"{own}/../../../elsewhere"],
                      ["-S", str(own), "-S", "/tmp/elsewhere"],
                      ["-S", f"{self.home.tmux_dir}/out/elsewhere"],
                      ["-S", f"{self.home.tmux_dir}/linked.sock"], ["-S", f"{own}\n"],
                      ["-S", str(own.with_name("other"))]):
            refused = self.home.run("tmux", *flags, "list-sessions")
            self.assertEqual(refused.code, 2, (flags, refused.err))
        kept = self.home.run("tmux", "-f/dev/null", "-L", "Sx", "-uLS", "list-sessions")
        self.assertNotEqual(kept.code, 2, kept.err)
        started = self.home.run("tmux", "-L", SOCKET, "new-session", "-d", "-s", "acme",
                                "sleep 600", env={"TMUX": "/tmp/elsewhere,1,0"})
        self.assertEqual(started.code, 0, started.err)
        self.assertEqual(self.home.tmux("has-session", "-t", "=acme").code, 0)
        # a seat's pane asks its own server by the path tmux gives it
        asked = self.home.run("tmux", "-S", str(own), "has-session", "-t", "=acme")
        self.assertEqual(asked.code, 0, asked.err)
        asked = self.home.run("tmux", "has-session", "-t", "=acme", env={"TMUX": f"{own},1,0"})
        self.assertEqual(asked.code, 0, asked.err)
        self.assertEqual(self.home.tmux("new-session", "-d", "-s", "beta", "sleep 600",
                                        server="other").code, 0)
        forgot = self.home.run("tmux", "has-session", "-t", "=beta",
                               env={"TMUX": f"{own.with_name('other')},1,0"})
        self.assertNotEqual(forgot.code, 0)
        pid = int(self.home.tmux("display-message", "-p", "-t", "=acme", "#{pid}").out)
        self.home.close()
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)


if __name__ == "__main__":
    unittest.main()
