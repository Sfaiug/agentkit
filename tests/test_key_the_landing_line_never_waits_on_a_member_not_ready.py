"""Unready members keep their place without holding checks or eligible fixers behind them.

Black-box through AK_BIN and Line's fake suites (tests/fixtures/akline.py).  A live member is a
process of this test's, recorded as `ak run` records itself, and inactive once the test ends it.
Each resume writes its refusal to a full pipe at log.txt. It stays alive until the pass ends,
so the lander cannot legitimately wake a head again because its resume already exited.
A rejoin is the woken run's own act, which the test plays between landings.
"""

from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import _strays, owner
from fixtures.akline import Line

SETTLE = 120    # seconds the runs a pass woke have to end


class LandingLineNeverWaits(unittest.TestCase):
    def setUp(self):
        self.line = Line({"t/ok.sh": "true\n"})
        self.addCleanup(self.line.close)
        self.logs = {}

    def member(self):
        n = len(self.line.members) + 1
        self.line.member({f"member-{n}.txt": f"{n}\n"})
        member = self.line.members[-1]
        os.mkfifo(member / "log.txt")
        pipe = open(member / "log.txt", "r+b", buffering=0)
        self.addCleanup(pipe.close)
        os.set_blocking(pipe.fileno(), False)
        self.logs[member.name] = pipe, fcntl.fcntl(pipe, fcntl.F_GETPIPE_SZ)
        return n

    def write(self, n, **changes):
        path = self.line.members[n - 1] / "run.json"
        state = json.loads(path.read_text())
        state.update(changes)
        path.write_text(json.dumps(state))

    def live(self, n, **changes):
        """Make member `n` active: its record owned by a live process, which runs until this
        test closes its input, or dies."""
        proc = subprocess.Popen(["cat"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.stdin.close)
        self.write(n, **owner(proc.pid), **changes)
        return proc

    def blame(self, n, after):
        wait = {**self.line.verdict(n), "fix": {"line": "fake red", "log": "suite.log"},
                "after": after}
        self.write(n, waiting_on=wait)
        return wait

    def rejoin(self, n):
        """Member `n`'s woken run rejoins the line, as a rejoining run writes it: in its place,
        its verdict spent."""
        self.write(n, waiting_on={key: self.line.verdict(n)[key] for key in ("line", "joined")})

    def land(self):
        """One lander pass, and one name for every resume that wrote to a member's log."""
        for pipe, size in self.logs.values():
            self.assertEqual(pipe.write(bytes(size)), size)

        # Each pass replaces its receipt on entry and exit. Hold the previous inode so even
        # a pass that ends before the first read is distinguishable from its predecessor.
        receipt = (self.line.members[0].parent / self.line.line).with_suffix(".passes")
        with receipt.open("ab") as previous, ThreadPoolExecutor(1) as pool:
            landing = pool.submit(self.line.land)
            try:
                while not landing.done():
                    with receipt.open() as current:
                        if (not os.path.sameopenfile(current.fileno(), previous.fileno())
                                and "started" not in json.load(current)):
                            break
                    time.sleep(0.1)
            finally:
                for pipe, size in self.logs.values():
                    pipe.read(size)
            done = landing.result()
        self.assertEqual(done.code, 0, done.out + done.err)
        deadline = time.monotonic() + SETTLE
        while _strays(self.line.home.root, self.line.home.tmux_dir):
            self.assertLess(time.monotonic(), deadline, "a woken run is still running")
            time.sleep(0.1)
        return sorted(name for name, (pipe, _) in self.logs.items()
                      for _ in (pipe.read() or b"").splitlines())

    def test_an_active_head_is_skipped_and_keeps_its_place_when_ready(self):
        for _ in range(3):
            self.member()
        head = self.live(1)
        before = (self.line.members[0] / "run.json").read_bytes()
        self.assertEqual(self.land(), ["fix-2"])
        self.assertEqual((self.line.members[0] / "run.json").read_bytes(), before)
        for n in (2, 3):
            tree = self.line.verdict(n)["land"]
            files = self.line.rig.git("ls-tree", "--name-only", tree).splitlines()
            self.assertNotIn("member-1.txt", files)
            self.write(n, state="pass", merged=True)
        self.member()
        head.stdin.close()
        head.wait()
        self.assertEqual(self.land(), ["fix-1"])
        self.assertEqual(self.line.verdict(1)["joined"], 1)
        self.assertEqual(self.line.verdict(4)["after"], {"fix-1": self.line.verdict(1)["land"]})

    def test_every_unblocked_red_wakes_even_behind_a_member_that_always_rejoins(self):
        for _ in range(3):
            self.member()
        waits = {n: self.blame(n, {"departed": "tree"}) for n in (2, 3)}
        for _ in range(2):
            self.assertEqual(self.land(), ["fix-1", "fix-2", "fix-3"])
            for n, wait in waits.items():
                self.assertEqual(self.line.verdict(n), wait)
            self.rejoin(1)

    def test_a_red_still_waiting_on_a_member_does_not_hold_the_tail(self):
        for _ in range(3):
            self.member()
        self.live(1)
        wait = self.blame(2, {"fix-1": "tree"})
        self.assertEqual(self.land(), ["fix-3"])
        self.assertEqual(self.line.verdict(2), wait)
        self.assertIn("land", self.line.verdict(3))

    def test_other_checkouts_on_unready_members_do_not_split_ready_stacks(self):
        for _ in range(3):
            self.member()
        other = str(self.line.home.path / "other-ak")
        self.live(2, ak_checkout=other)
        wait = self.blame(3, {"fix-1": "tree"})
        self.write(3, ak_checkout=other)
        for _ in range(2):
            tail = self.member()
            self.assertEqual(self.land(), ["fix-1"])
            files = self.line.rig.git("ls-tree", "--name-only",
                                      self.line.verdict(tail)["land"]).splitlines()
            self.assertIn("member-1.txt", files)
            self.assertIn(f"member-{tail}.txt", files)
            for n in (2, 3):
                self.assertNotIn(f"member-{n}.txt", files)
            self.assertEqual(self.line.verdict(3), wait)
            self.write(tail, state="pass", merged=True)
            self.rejoin(1)


if __name__ == "__main__":
    unittest.main()
