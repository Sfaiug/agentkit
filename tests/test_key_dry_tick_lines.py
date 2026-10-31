"""`ak watch --dry-run` says first who holds the tick lock and how big the tick's log is, then
why it skips GitHub, and writes nothing.

A person or a model runs the dry tick on a live host where cron's tick may be running beside
it, so its first line says whether a tick holds the lock, its pid and for how long, and how near
watch.log is to the 5 MB it is rolled at; whoever holds the lock, the dry run goes on.  With no
GitHub to ask, its last line says why in gh's own words made one line, and a logged-out gh, the
owner's to fix, is said apart from an outage or no gh at all.  A real tick records that logout
for every seat to say; a dry one leaves every file under HOME as it was.  Each Home holds a
config and, where a test says, the lock or the log; the lock's holder is this test, as
tests/test_key_tick_lock_held.py holds it.  What a dry tick asks GitHub is
tests/test_key_tick_dry_run.py's to judge.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, against the scripted gh of tests/fixtures/fakegh.py.
"""

import fcntl
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.fakegh import LOGGED_OUT, OFFLINE, GitHub
from test_key_tick_gh_out import without_gh
from test_key_tick_lock_held import LOCK, MINUTE, SLACK

FREE = "lock free · watch.log 0.0 MB of 5 MB"
HELD = "lock held by pid 4242 for {} min · watch.log 0.0 MB of 5 MB"
OUT = "gh is not logged in; PR checks skipped ("
DOWN = "WARN GitHub is unavailable; PR checks skipped ("
# more after gh's own words: runs of tabs, spaces and blank lines, and past 160 characters
MORE = "\n\n\tRequest ID:   C0DE:1A2B:3C4D5E:6F7A8B:65A1B2C3\n\t  see  https://docs.github.com/rest\n"


def skipped(start, said):
    """The line starting `start` that gives what gh `said`: each run of whitespace one space,
    none at either end, cut at 160 characters."""
    return f"{start}{' '.join(said.split())[:160]})"


def files(root):
    """Every path under `root` with its mode, and each file's bytes and when it changed."""
    return {str(path.relative_to(root)): (path.lstat().st_mode, *(
                (path.read_bytes(), path.lstat().st_mtime_ns) if path.is_file() else ()))
            for path in root.rglob("*")}


class DryTick(unittest.TestCase):
    def home(self, said=LOGGED_OUT, code=4):
        """A Home holding a config, whose gh says `said` and exits `code` to every call: 4 is
        gh's own exit for a login it lacks."""
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        GitHub(home).reply("", err=said, code=code)
        return home

    def dry(self, home, env=None):
        """The lines `ak watch --dry-run` printed, once it exited 0 with nothing on stderr and
        left every file under HOME as it was."""
        before = files(home.path)
        done = home.ak("watch", "--dry-run", env=env)
        self.assertEqual((done.code, done.err), (0, ""), done.out)
        after = files(home.path)
        self.assertEqual(sorted(path for path in before.keys() | after.keys()
                                if before.get(path, 0) != after.get(path, 0)), [])
        return done.out.splitlines()

    def test_a_logged_out_gh_is_said_in_its_own_words_and_recorded_nowhere(self):
        for said in (LOGGED_OUT, LOGGED_OUT + MORE):
            with self.subTest(said=said):
                self.assertEqual(self.dry(self.home(said)), [FREE, skipped(OUT, said)])

    def test_an_unavailable_github_is_a_warning_in_gh_s_own_words(self):
        for said in (OFFLINE, OFFLINE + MORE):
            with self.subTest(said=said):
                self.assertEqual(self.dry(self.home(said, code=1)), [FREE, skipped(DOWN, said)])

    def test_no_gh_on_path_is_an_unavailable_github(self):
        home = self.home()
        lines = self.dry(home, {"PATH": without_gh(home)})
        self.assertEqual(home.calls("gh"), [])     # the Home's gh was out of reach
        self.assertEqual(len(lines), 2, lines)
        self.assertEqual(lines[0], FREE)
        self.assertTrue(lines[1].startswith(DOWN), lines)

    def test_a_log_of_one_and_a_half_megabytes_reads_so(self):
        home = self.home()
        home.write(".agentkit/tmp/watch.log", "x" * (3 * 1024 * 1024 // 2))
        self.assertEqual(self.dry(home), ["lock free · watch.log 1.5 MB of 5 MB",
                                          skipped(OUT, LOGGED_OUT)])

    def test_a_held_lock_is_named_by_its_pid_and_minutes_and_the_dry_run_goes_on(self):
        home = self.home()
        lock = home.write(LOCK, "4242\n", ago=5 * MINUTE + SLACK)
        with lock.open("a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            began, before = lock.stat().st_mtime, time.time()
            lines = self.dry(home)
            # each whole minute it was held while ak ran: a slow start may read a later one
            ages = range(int(before - began) // MINUTE, int(time.time() - began) // MINUTE + 1)
        self.assertIn(lines, [[HELD.format(age), skipped(OUT, LOGGED_OUT)] for age in ages])
        # let go, it is the file a tick that ended leaves, and nobody holds the lock
        self.assertEqual(self.dry(home)[0], FREE)


if __name__ == "__main__":
    unittest.main()
