"""`ak watch` runs one whole tick, keeps its state in watch.json and holds the one-tick lock.

Cron starts a tick every few minutes whatever the last one is doing, so a tick holds a lock on
state/watch.tick.lock for its whole run, and a tick that finds it held runs nothing and says
whose it is, and that it may be hung once it has held it half an hour.  What the ticks remember
between them is the JSON object state/watch.json, with the boot it was written in, which the
menu and the next tick read.  Anything but `--dry-run` after `ak watch` is a usage error that
runs nothing: models learn the command by typing at it.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, its GitHub tests/fixtures/fakegh.py; this
test fails against `/bin/false`.
"""

import fcntl
import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home
from fixtures.fakegh import GitHub
from fixtures import akconfig

KEPT = ("reviewed", "own", "stalls", "seen_at", "after_merge")
BOOT = Path("/proc/sys/kernel/random/boot_id")
USAGE = "ak watch: usage: ak watch [--dry-run]  (got {!r})\n"


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class OneTick(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        GitHub(home)
        cls.state = home.path / ".agentkit" / "state"
        cls.tick = home.tick()

    def test_a_tick_succeeds_and_keeps_its_state_in_watch_json(self):
        self.assertEqual(self.tick.code, 0, self.tick.err)
        kept = json.loads((self.state / "watch.json").read_text())
        self.assertEqual({key: type(kept.get(key)) for key in KEPT}, dict.fromkeys(KEPT, dict))
        self.assertEqual(kept["boot_id"], BOOT.read_text().strip() if BOOT.exists() else None)

    def test_a_tick_asks_github_who_the_owner_is(self):
        self.assertIn(["api", "user"], self.home.calls("gh"))

    def test_a_tick_with_no_seat_and_no_run_touches_none_of_the_owners_units(self):
        self.assertEqual(self.tick.code, 0, self.tick.err)
        for tool in ("systemctl", "systemd-run", "loginctl"):
            with self.subTest(tool):
                self.assertEqual(self.home.calls(tool), [])

    def test_a_tick_finding_the_lock_held_runs_nothing_and_says_whose_it_is(self):
        kept = (self.state / "watch.json").read_bytes()
        asked = len(self.home.calls("gh"))
        held = "tick already running (pid 4242, for {} min)\n"
        hung = ("WARN the tick holding the lock has been running for {} min; look at it, "
                "and kill it if it is hung\n")
        for ago in (2400, 0):
            with self.subTest(ago=ago):
                lock = self.home.write(".agentkit/state/watch.tick.lock", "4242\n", ago=ago)
                with lock.open("r") as holder:
                    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    began = lock.stat().st_mtime
                    before = time.time()
                    done = self.home.ak("watch")
                    after = time.time()
                # The subprocess can read either side of a minute boundary.
                ages = range(int((before - began) // 60), int((after - began) // 60) + 1)
                self.assertEqual((done.code, done.err), (0, ""))
                self.assertIn(done.out, [held.format(age) + (hung.format(age) if age >= 30 else "")
                                         for age in ages])
                self.assertEqual((self.state / "watch.json").read_bytes(), kept)
                self.assertEqual(len(self.home.calls("gh")), asked)

    def test_anything_but_dry_run_is_a_usage_error_that_runs_nothing(self):
        with Home() as home:
            for args in (["x"], ["--bogus"], ["x", "--dry-run"], ["--dry-run", "x"]):
                with self.subTest(args=args):
                    done = home.ak("watch", *args)
                    self.assertEqual((done.code, done.out, done.err),
                                     (2, "", USAGE.format(args[0])))
            self.assertEqual(list((home.path / ".agentkit" / "state").iterdir()), [])
            self.assertEqual(home.calls("gh"), [])
            self.assertNotEqual(home.tmux("list-sessions").code, 0)


if __name__ == "__main__":
    unittest.main()
