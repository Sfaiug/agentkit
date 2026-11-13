"""A green line wakes only its head, the first green delivery, and each end of a delivery the
next; a head whose resume is coming up is not woken again till it ends, and fixes wake as before.

On 13 Nov 2026 a green stack of 41 woke 41 runs: the load went from 125 to 215 on 18 cores and one
merged every ~100 s, against 15 to 25 s uncontended, as only the first can take the merge lock.
Black-box through AK_BIN and Line's fake suites (tests/fixtures/akline.py).  A wake is read from
what the woken run leaves once every resume of the Home has ended: the line its `ak run resume`,
refused at once, writes to the run's log.txt.  The end of a delivery is the delivering run's own
act, which the test plays while a pass holds on a member whose tree has `hold.txt`.  A resume
coming up is a process of this test's whose arguments end as one's do, `run resume <id>`.
"""

from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import _strays
from fixtures.akline import READINGS, Line

SETTLE = 300    # seconds a woken run, or the pass's next wake, has
HOLD = """storage=$(git rev-parse --git-common-dir)
[ -f hold.txt ] || exit 0
touch "$storage/reached"
until [ -f "$storage/go" ]; do sleep 0.1; done
"""
RED = {"line": "a required check is red", "log": "checks.log"}


class DeliveriesPassABaton(unittest.TestCase):
    def setUp(self):
        self.line = Line({"t/ok.sh": "true\n", "t/hold.sh": HOLD})
        self.addCleanup(self.line.close)
        self.storage = self.line.rig.path / ".git"
        self.seen, self.fakes = Counter(), set()

    def member(self, **files):
        n = len(self.line.members) + 1
        self.line.member({f"member-{n}.txt": f"{n}\n", **files})

    def write(self, n, **changes):
        """Member `n`'s record with `changes`, written whole, as a run writes its own."""
        path = self.line.members[n - 1] / "run.json"
        fresh = path.with_name("run.json.new")
        fresh.write_text(json.dumps({**json.loads(path.read_text()), **changes}))
        fresh.replace(path)

    def coming_up(self, n):
        """A resume of member `n` coming up, till the test closes its input."""
        proc = subprocess.Popen(["sh", "-c", "read _", "sh", "run", "resume", f"fix-{n}"],
                                stdin=subprocess.PIPE, start_new_session=True,
                                env={"HOME": self.line.home.env["HOME"], "PATH": os.defpath})
        self.fakes.add(proc.pid)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.stdin.close)
        return proc

    def resuming(self):
        """The Home's `ak run resume` processes but the test's own."""
        found = []
        for pid in set(_strays(self.line.home.path)) - self.fakes:
            try:
                if b"resume" in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0"):
                    found.append(pid)
            except OSError:
                continue
        return found

    def logged(self):
        return Counter({member.name: len((member / "log.txt").read_text().splitlines())
                        for member in self.line.members if (member / "log.txt").exists()})

    def woken(self, at_least=0, lander=None):
        """The members woken since the last ask, by name, once `at_least` are and every resume
        they started has ended."""
        deadline = time.monotonic() + SETTLE
        while sum((self.logged() - self.seen).values()) < at_least or self.resuming():
            if lander is not None:
                self.assertIsNone(lander.poll(), self.said.read_text())
            self.assertLess(time.monotonic(), deadline, "no wake came, or a woken run still runs")
            time.sleep(0.2)
        now = self.logged()
        woken, self.seen = sorted((now - self.seen).elements()), now
        return woken

    def land(self):
        """One lander pass, and the members it woke."""
        done = self.line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        return self.woken()

    def hold(self):
        """A pass started and held on the check of the member with `hold.txt`."""
        lander = self.line.home.spawn("run", "--lander", self.line.line,
                                      env={"AK_HOST_READINGS": READINGS})
        self.said = self.line.home.log("spawn-1.err")    # one pass held a test
        deadline = time.monotonic() + SETTLE
        while not (self.storage / "reached").exists():
            self.assertIsNone(lander.poll(), self.said.read_text())
            self.assertLess(time.monotonic(), deadline, "the held member was never checked")
            time.sleep(0.2)
        return lander

    def release(self, lander):
        (self.storage / "go").touch()
        self.assertEqual(lander.wait(timeout=SETTLE), 0, self.said.read_text())

    def test_a_green_stack_wakes_its_head_and_each_end_of_a_delivery_the_next(self):
        for _ in range(4):
            self.member()
        self.assertEqual(self.land(), ["fix-1"])
        for n in range(1, 5):
            self.assertIn("land", self.line.verdict(n))
        self.member(**{"hold.txt": "x\n"})
        lander = self.hold()
        self.assertEqual(self.woken(), ["fix-1"], "a pass on saved verdicts woke more than the head")
        self.write(1, state="pass", merged=True)
        self.assertEqual(self.woken(1, lander), ["fix-2"], "a merge did not hand on the turn")
        self.write(2, waiting_on={key: self.line.verdict(2)[key] for key in ("line", "joined")})
        self.assertEqual(self.woken(1, lander), ["fix-3"], "a rejoin did not hand on the turn")
        self.write(3, waiting_on={**self.line.verdict(3), "fix": RED})
        self.assertEqual(self.woken(2, lander), ["fix-3", "fix-4"],
                         "a red delivery was not woken to fix, or did not hand on the turn")
        self.release(lander)
        self.assertEqual(self.woken(), [])

    def test_a_head_coming_up_is_woken_only_once_its_resume_has_ended(self):
        for _ in range(3):
            self.member()
        resume = self.coming_up(1)
        self.assertEqual(self.land(), [], "a head was woken while its resume came up")
        self.member(**{"hold.txt": "x\n"})
        lander = self.hold()
        self.assertEqual(self.woken(), [])
        resume.stdin.close()
        resume.wait()
        self.assertEqual(self.woken(1, lander), ["fix-1"], "the pass did not wake a head left parked")
        self.release(lander)
        self.assertEqual(self.woken(), [], "a pass woke its head twice")
        self.assertEqual(self.land(), ["fix-1"], "a head whose resume refused was not woken again")

    def test_fix_verdicts_wake_as_before(self):
        for _ in range(3):
            self.member()
        self.write(2, waiting_on={**self.line.verdict(2), "fix": RED, "after": {"departed": "tree"}})
        self.assertEqual(self.land(), ["fix-1", "fix-2"])
        self.assertIn("land", self.line.verdict(3))


if __name__ == "__main__":
    unittest.main()
