"""A red stack's narrowing probes many stacks at once on the suite helpers, one round at a time,
and only the step that decides the blame runs on this host; a red only the machine shows that
passes there moves the narrowing on above it.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py; ssh runs what it is given on `acme-linux`, the Linux machine of
tests/fixtures/akmachine.py, with room for four pieces at once.  Of eight members the sixth makes
one test fail.  Each member has its row in the Home's history.db, where each probe leaves one.
"""

import contextlib
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine
from fixtures.akbin import Home
from fixtures.akline import SUITE, Line
from test_key_history_db import ORIGINAL

# Here, the test notes the stack it ran on.  A run of just it on the machine, a probe, waits until
# another probe is under way beside it, at most a minute, and once one was, notes so: under way
# together.
BAD = """if [ "${container:-}" != docker ]; then
  echo $(ls member-*) >>"$(git rev-parse --git-common-dir)/here"
elif [ -n "${AK_ONLY:-}" ]; then
  touch "PROBES/$$"
  i=0
  until [ -f PROBES.together ] || [ $i -ge 600 ]; do
    [ "$(ls PROBES | wc -l)" -lt 2 ] || touch PROBES.together
    sleep 0.1; i=$((i + 1))
  done
  rm "PROBES/$$"
fi
test -z "$(ls bad-* 2>/dev/null)"
"""


class ARedStackNarrowsAtOnceOnTheHelpers(unittest.TestCase):
    def land(self, tests, changes, home=None):
        """The line of eight members, member n adding `changes[n]`, checked once: the sixth goes
        to its fixer for bad.sh, and the others land."""
        line = Line({**tests, "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"},
                    home=home)
        self.addCleanup(line.close)
        akconfig.write(line.home, ["opus", "astra"], settings={"suite_helper": "acme-linux"})
        self.machine = akmachine.install(line.home, cpus=8)
        self.history = line.home.path / ".agentkit" / "history.db"
        # a run with no row keeps no checks
        with contextlib.closing(sqlite3.connect(self.history)) as db:
            db.execute("CREATE TABLE runs (%s)" % ", ".join(map(" ".join, ORIGINAL)))
            db.executemany("INSERT INTO runs (run_id) VALUES (?)",
                           [(f"fix-{n}",) for n in range(1, 9)])
            db.commit()
        for n in range(1, 9):
            line.member({f"member-{n}.txt": f"{n}\n", **changes.get(n, {})})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        for n in range(1, 9):
            self.assertEqual([key for key in ("land", "fix") if key in line.verdict(n)],
                             ["fix"] if n == 6 else ["land"], n)
        self.assertEqual(line.verdict(6)["fix"]["tests"], ["bad.sh"])
        return line

    def test_probes_run_together_there_and_only_the_deciding_step_runs_here(self):
        home = Home()
        probes = home.root / "probes"
        probes.mkdir()
        line = self.land({"t/bad.sh": BAD.replace("PROBES", str(probes)), "t/ok.sh": "true\n"},
                         {6: {"bad-6.txt": "x\n"}}, home)
        self.assertTrue(probes.with_suffix(".together").exists(), "no two probes ran at once")
        probed = [run for log in self.machine.glob("docker/roots/*/home/ak/work/.git/suite.log")
                  for run in log.read_text().splitlines() if run.startswith("alone")]
        # each probe's row: a piece's names its share
        with contextlib.closing(sqlite3.connect(self.history)) as db:
            rows = db.execute("SELECT run_id FROM checks WHERE kind = 'landing' AND "
                              "command = ? AND place = 'acme-linux'", (SUITE,)).fetchall()
        self.assertEqual(len(rows), len(probed), rows)
        here = set((line.rig.path / ".git" / "here").read_text().splitlines())
        # Bisecting here ran it on four: the deepest stack, whose piece failed on the machine,
        # then the stacks up to members 4, 6 and 5.
        self.assertLess(len(here), 4, here)

    def test_a_red_only_the_machine_shows_passes_here_and_the_narrowing_goes_on_above_it(self):
        # bad.sh fails on the machine on the stack of member 1 alone, which also fails
        # transient.sh, mended by member 2: a whole check of that stack would blame member 1
        self.land({"t/bad.sh": '[ "${container:-}" != docker ] || [ -f member-2.txt ] || exit 1\n'
                               "test ! -f bad-6.txt\n",
                   "t/transient.sh": "test ! -f transient.txt || test -f fixed.txt\n"},
                  {1: {"transient.txt": "x\n"}, 2: {"fixed.txt": "x\n"}, 6: {"bad-6.txt": "x\n"}})


if __name__ == "__main__":
    unittest.main()
