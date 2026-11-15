"""`ak standby ALIAS` keeps this machine's own job before its pass: one crontab line, which makes
the pass again every three minutes and keeps none of its output, one however often the command
runs, every other line kept byte for byte; a first pass whose home did not answer leaves it all
the same.  `ak standby` names the home this machine copies and the copy's age, from when the last
pass that ended well began, and exits 0 only for a copy of that home: never before the first
pass, nor once this machine is another home's client.  The age is the older of this machine's
two clocks': with its wall clock set back an hour since the pass and ten minutes gone since boot,
the copy is 10 minutes old.  A pass whose home did not answer exits non-zero and leaves the copy
and its age going on, and one while a pass is under way copies nothing, though a pass that died
holds none back.  Black-box, through tests/fixtures/twohomes.py, whose machine takes its clocks
from AK_NOW (`wall seconds-since-boot boot`), one of its variables.
"""

import os
from pathlib import Path
import shlex
import signal
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

# every byte of it kept, the line that names the job's mark too
TABLE = (b"# the owner's\n\n0 4 * * * /usr/bin/true # caf\xe9\n"
         b"0 5 * * * echo '# agentkit standby' is watched >/dev/null\n")
STATE = ".agentkit/state/watch.json"     # the home's, which a pass copies
PASSED = "1789000000 10000 acme-boot-1"      # this machine's clocks at its pass
SET_BACK = "1788996400 10600 acme-boot-1"    # ten minutes on since boot, the wall an hour back
FAILED = "1789000120 10120 acme-boot-1"      # two minutes after the pass
LATER = "1789000600 10600 acme-boot-1"       # ten minutes after it


def minutes(count):
    """An age of `count` minutes, a word of its own."""
    return rf"(?<![\w-]){count}m(?![\w-])"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AStandbysJobAndAge(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        self.addCleanup(home.answer)
        here.client_of(home)
        home.write(STATE, "the home's first")
        self.table = here.root / "crontab"
        self.table.write_bytes(TABLE)

    def ak(self, *args, now):
        self.here.env["AK_NOW"] = now
        return self.here.ak(*args)

    def job(self):
        """The crontab's lines past the owner's, which stay as they were."""
        table = self.table.read_bytes()
        self.assertEqual(table[:len(TABLE)], TABLE)
        return table[len(TABLE):].decode().splitlines()

    def test_the_job_is_one_line_however_often_and_makes_the_pass(self):
        home, here = self.home, self.here
        for _ in range(2):
            done = self.ak("standby", home.name, now=PASSED)
            self.assertEqual(done.code, 0, done.out + done.err)
            [line] = self.job()
        self.assertEqual(line.split()[:5], ["*/3", "*", "*", "*", "*"])
        home.write(STATE, "the home's second")
        done = here.run("/bin/sh", "-c", line.split(None, 5)[5])    # as cron runs it
        self.assertEqual((done.code, done.out, done.err), (0, "", ""))
        self.assertEqual(here.tree()[STATE], b"the home's second")
        self.assertEqual(self.job(), [line])

    def test_the_copys_age_is_the_older_of_its_two_clocks_and_of_its_homes_copy_alone(self):
        home, here = self.home, self.here
        said = self.ak("standby", now=PASSED)
        self.assertNotEqual(said.code, 0, said.out)
        done = self.ak("standby", home.name, now=PASSED)
        self.assertEqual(done.code, 0, done.out + done.err)
        said = self.ak("standby", now=SET_BACK)
        self.assertEqual(said.code, 0, said.out + said.err)
        self.assertIn(home.name, said.out)
        self.assertRegex(said.out, minutes(10))
        here.write(".agentkit/state/server", "acme-laptop\n")     # another home's client now
        said = self.ak("standby", now=SET_BACK)
        self.assertNotEqual(said.code, 0, said.out)

    def test_a_pass_whose_home_did_not_answer_leaves_the_copy_and_its_age_going_on(self):
        home, here = self.home, self.here
        done = self.ak("standby", home.name, now=PASSED)
        self.assertEqual(done.code, 0, done.out + done.err)
        home.write(STATE, "the home's second")
        before = here.copy()
        home.silence()
        done = self.ak("standby", home.name, now=FAILED)
        self.assertNotEqual(done.code, 0)
        self.assertEqual(here.copy(), before)
        said = self.ak("standby", now=LATER)
        self.assertIn(home.name, said.out)
        self.assertRegex(said.out, minutes(10))

    def test_a_first_pass_whose_home_did_not_answer_leaves_the_job(self):
        self.home.silence()
        done = self.ak("standby", self.home.name, now=PASSED)
        self.assertNotEqual(done.code, 0)
        self.assertEqual(len(self.job()), 1)
        said = self.ak("standby", now=LATER)
        self.assertNotEqual(said.code, 0, said.out)

    def test_a_pass_while_one_is_under_way_copies_nothing_and_one_that_died_holds_none_back(self):
        home, here = self.home, self.here
        # the home's rsync, reached, never answers
        reached = home.root / "reached"
        home.fake("rsync", f"#!/bin/sh\n: >{shlex.quote(str(home.at / reached.name))}\n"
                           "exec sleep 600\n")
        here.env["AK_NOW"] = PASSED
        under_way = here.spawn("standby", home.name)
        for _ in range(600):
            if reached.exists():
                break
            time.sleep(0.1)
        self.assertTrue(reached.exists(), here.log("spawn-1.err").read_text())
        home.write(STATE, "the home's second")
        before = here.copy()
        done = self.ak("standby", home.name, now=PASSED)
        self.assertNotEqual(done.code, 0)
        self.assertEqual(here.copy(), before)
        os.killpg(under_way.pid, signal.SIGKILL)
        under_way.wait()
        (home.bin / "rsync").unlink()
        done = self.ak("standby", home.name, now=PASSED)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(here.tree()[STATE], b"the home's second")


if __name__ == "__main__":
    unittest.main()
