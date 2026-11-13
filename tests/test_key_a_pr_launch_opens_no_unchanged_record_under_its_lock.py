"""A launch on a pull request opens no unchanged run record while it holds the slot lock.

Before it admits a launch on a pull request, ak looks for another run going on it, under the
slot lock so that of two launches at once the second sees the first.  A host keeps thousands of
ended runs, and each record the launch had already read before taking the lock was opened and
parsed again under it, holding every other admission back.  Black-box: the program `AK_BIN`
names reviews a pull request from outside through tests/fixtures/akbin.py, against the bare
origin of gitrig.py and the GitHub of fakegh.py, with a scripted reviewer from fakeadapter.py.
An ended run's record, unchanged for over a second, carries a write lease, which holds whoever
opens it until the lease is let go; /proc/locks names that opener and the slot lock's holder.
"""

import errno
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

RULES = "---\ntests: test -f contrib.txt\n---\n# widget\n"
PASSED = "20261113-1000-acme-passed"
ENDED = {"run_id": PASSED, "title": "passed", "state": "pass", "verdict": "PASS"}


def opener_holds(record, lock):
    """Whether a process waiting to open `record` on its lease holds `lock` meanwhile: in
    /proc/locks a lease's waiters follow it, `->`, on its own number."""
    rows = [line.split() for line in Path("/proc/locks").read_text().splitlines()]

    def on(path, row):
        return path.exists() and row[5].rsplit(":", 1)[-1] == str(path.stat().st_ino)

    holders = {row[4] for row in rows if row[1] == "FLOCK" and on(lock, row)}
    leases = {row[0] for row in rows if row[1] == "LEASE" and on(record, row)}
    return any(row[0] in leases and row[1] == "->" and row[5] in holders for row in rows)


def lease(fd):
    """A write lease on the file open at `fd`, once no one else has it open."""
    while True:
        try:
            return fcntl.fcntl(fd, fcntl.F_SETLEASE, fcntl.F_WRLCK)
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EBUSY):
                raise
        time.sleep(0.005)


class APrLaunchOpensNoUnchangedRecordUnderItsLock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig = Rig(home, "widget", files={"AGENTS.md": RULES})
        gh = GitHub(home)
        rig.branch("contrib", {"contrib.txt": "c\n"})
        url = gh.open_pr(rig, "contrib", title="Add contrib", body="adds a file",
                         author="other-dev")
        akconfig.write(home, ["opus"])
        fakeadapter.install(home, claude="pass")
        record = home.write(f".agentkit/runs/{PASSED}/run.json", ENDED)
        lock = record.parent.parent / ".slots.lock"
        while time.time_ns() - record.stat().st_ctime_ns < 1_100_000_000:
            time.sleep(0.05)    # a record written within the second may be read again
        # a broken lease signals its holder, which by default would end this test
        cls.addClassCleanup(signal.signal, signal.SIGIO, signal.signal(signal.SIGIO,
                                                                       signal.SIG_IGN))
        fd = os.open(record, os.O_WRONLY)
        cls.addClassCleanup(os.close, fd)
        lease(fd)
        launch = home.spawn("run", "--review-pr", url)
        opened, under = 0, False
        deadline = time.monotonic() + 300
        while not under and launch.poll() is None and time.monotonic() < deadline:
            if fcntl.fcntl(fd, fcntl.F_GETLEASE) == fcntl.F_WRLCK:
                time.sleep(0.005)
                continue
            opened += 1
            with lock.open("a") as held:
                # the slot lock held while the lease is let go and taken back, so no open
                # under it slips by in between
                while not (under := opener_holds(record, lock)):
                    try:
                        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        time.sleep(0.005)
                fcntl.fcntl(fd, fcntl.F_SETLEASE, fcntl.F_UNLCK)
                if not under:
                    lease(fd)
        launch.wait(timeout=max(deadline - time.monotonic(), 1))
        cls.opened, cls.under, cls.code = opened, under, launch.returncode
        cls.state = next((json.loads(path.read_text()) for path in
                          sorted(record.parent.parent.glob("*-review-pr-widget-*/run.json"))),
                         {})

    def test_the_launch_opens_no_unchanged_record_while_it_holds_the_slot_lock(self):
        self.assertGreater(self.opened, 0)      # the lease saw the launch read it
        self.assertFalse(self.under)

    def test_the_review_still_runs_to_its_verdict(self):
        self.assertEqual(self.code, 0, self.home.log("spawn-1.err").read_text())
        self.assertEqual(self.state.get("verdict"), "PASS")


if __name__ == "__main__":
    unittest.main()
