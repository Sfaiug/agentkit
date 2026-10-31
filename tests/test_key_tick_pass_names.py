"""A tick's pass that raises is one WARN line naming it, and a pass that ran writes none.

Each pass of the tick has a name, one to three lowercase words, and the one place the passes run
builds the WARN line of one that raises from it: `WARN <name> did not run: <why>`, so a log line
or `ak doctor` can name the pass.  Here the switch retirement pass raises, finding a directory
where its record is kept.  Cron appends a tick's output to watch.log, so what the tick prints is
what the log gets.  Black-box: the program `AK_BIN` names ticks from outside through
tests/fixtures/akbin.py, its GitHub tests/fixtures/fakegh.py; this test fails against
`/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home
from fixtures.fakegh import GitHub
from fixtures import akconfig

NAMED = re.compile(r"WARN [a-z]+(?: [a-z]+){0,2} did not run: \S.*")


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class TickPassNames(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        GitHub(self.home)

    def warned(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.err)
        return [line for line in done.out.splitlines() if line.startswith("WARN")]

    def test_a_tick_whose_passes_all_ran_writes_no_warn(self):
        self.assertEqual(self.warned(), [])

    def test_a_pass_that_raises_is_one_warn_line_naming_it_in_a_few_words(self):
        (self.home.path / ".agentkit" / "state" / "retire.json").mkdir()
        warned = self.warned()
        self.assertEqual(len(warned), 1, warned)
        self.assertTrue(NAMED.fullmatch(warned[0]), warned[0])


if __name__ == "__main__":
    unittest.main()
