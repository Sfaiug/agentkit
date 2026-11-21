"""A home keeps a record of each machine that says it copied it as a pass does, `ak standby
--began` there and then `ak standby --copied HOST WALL SINCE BOOT yes|no`: the stamp it printed,
handed back, and whether that machine takes over; `ak standby` there lists one line for each, how
old its copy is by the home's clocks and if it takes over, or says that no machine copies it, and
exits 0.  A record never goes into a standby's own folder, another host name's leaves it byte for
byte, a request outside the grammar writes nothing, one that cannot be written exits 1 in one
line, and a record that cannot be read is listed as such, one of many short words at under 8 MiB
more memory than one of a single word.  On a client the request is kept and `ak standby` shows
what it showed.  Black-box, through
tests/fixtures/akbin.py, with the home's clocks from AK_NOW (`wall seconds-since-boot boot`).
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

RECORDS = ".agentkit/tmp/copies"      # the home's records of the machines that copy it
OWN = ".agentkit/tmp/standby"       # a standby's own folder, which makes a client one
TOLD = "1789000000 50000 acme-boot-1"      # the home's clocks at a request
LATER = "1789000300 50300 acme-boot-1"     # five minutes on
SET_BACK = "1788996700 50300 acme-boot-1"  # five minutes on since boot, the wall an hour back
# Run a command and print, last on stderr, the most memory any process of it held, in bytes.
PEAK = ("import resource, subprocess, sys\n"
        "code = subprocess.run(sys.argv[1:]).returncode\n"
        "held = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss\n"
        "print(held * (1 if sys.platform == 'darwin' else 1024), file=sys.stderr)\n"
        "sys.exit(code)")


def minutes(count):
    """An age of `count` minutes, a word of its own."""
    return rf"(?<![\w-]){count}m(?![\w-])"


class AHomeKnowsItsStandby(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def ak(self, *args, now=TOLD):
        self.home.env["AK_NOW"] = now
        return self.home.ak("standby", *args)

    def began(self, now=TOLD):
        """The words of the stamp `ak standby --began` prints on the home."""
        done = self.ak("--began", now=now)
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out.split()

    def told(self, host, takes, now=TOLD):
        """`host`'s request, as a pass makes it: the home's stamp, handed back."""
        done = self.ak("--copied", host, *self.began(now), takes, now=now)
        self.assertEqual(done.code, 0, done.out + done.err)

    def listed(self, now=TOLD):
        """Each line `ak standby` on the home says, ending well."""
        said = self.ak(now=now)
        self.assertEqual(said.code, 0, said.out + said.err)
        return said.out.splitlines()

    def line(self, lines, name):
        [line] = [line for line in lines if name in line]
        return line

    def record(self, name):
        return (self.home.path / RECORDS / name).read_bytes()

    def test_a_home_that_got_no_request_says_none_copies_it(self):
        self.assertIn("no machine", "\n".join(self.listed()))

    def test_a_copys_age_is_by_the_homes_clocks_from_the_stamp_it_was_handed(self):
        self.told("acme-vm", "no")
        [line] = self.listed()
        self.assertIn("acme-vm", line)
        self.assertRegex(line, "<1m")
        self.assertRegex(self.line(self.listed(LATER), "acme-vm"), minutes(5))
        self.assertRegex(self.line(self.listed(SET_BACK), "acme-vm"), minutes(5))
        self.assertNotIn(OWN, self.home.tree())

    def test_a_machine_that_takes_over_is_listed_so_till_its_next_request_without(self):
        self.told("acme-vm", "yes")
        self.assertIn("takes over", self.line(self.listed(), "acme-vm"))
        self.told("acme-vm", "no")
        self.assertNotIn("takes over", self.line(self.listed(), "acme-vm"))

    def test_a_second_host_names_request_leaves_the_first_ones_record(self):
        self.told("acme-vm", "no")
        record = self.record("acme-vm")
        self.told("acme-mac", "yes", now=LATER)
        self.assertEqual(self.record("acme-vm"), record)
        lines = self.listed(LATER)
        self.assertEqual(len(lines), 2, lines)
        self.assertRegex(self.line(lines, "acme-vm"), minutes(5))
        self.assertRegex(self.line(lines, "acme-mac"), "<1m")

    def test_a_client_keeps_the_request_and_shows_what_it_showed(self):
        self.home.write(".agentkit/state/server", "acme-mini\n")
        before = self.ak()
        self.told("acme-vm", "no")
        self.assertIn(f"{RECORDS}/acme-vm", self.home.tree())
        self.assertNotIn(OWN, self.home.tree())
        self.assertEqual(self.ak(), before)

    @unittest.skipIf(os.geteuid() == 0, "root reads a file whatever its mode")
    def test_a_record_that_cannot_be_read_is_listed_as_such_beside_the_rest(self):
        self.told("acme-vm", "no")
        self.home.write(f"{RECORDS}/acme-laptop", "not a record\n")
        self.home.write(f"{RECORDS}/acme-mac", "").chmod(0)
        lines = self.listed(LATER)
        self.assertIn("cannot be read", self.line(lines, "acme-laptop"))
        self.assertIn("cannot be read", self.line(lines, "acme-mac"))
        self.assertRegex(self.line(lines, "acme-vm"), minutes(5))

    def test_a_record_of_many_short_words_costs_little_more_than_one_of_one_word(self):
        def peak(words):
            self.home.write(f"{RECORDS}/acme-mac", words + "\nno\n")
            self.home.env["AK_NOW"] = LATER
            said = self.home.run(sys.executable, "-c", PEAK, self.home.program, "standby")
            self.assertEqual(said.code, 0, said.out + said.err)
            self.assertIn("cannot be read", said.out)
            return int(said.err.splitlines()[-1])
        one = peak("a" * 990000)
        self.assertLess(peak("ac " * 330000), one + 8 * 2**20)

    @unittest.skipIf(os.geteuid() == 0, "root writes a folder whatever its mode")
    def test_a_record_that_cannot_be_written_says_so_in_one_line(self):
        self.told("acme-vm", "no")
        records = self.home.path / RECORDS
        records.chmod(0o555)
        self.addCleanup(records.chmod, 0o755)
        done = self.ak("--copied", "acme-mac", *self.began(), "no")
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual(len(done.err.splitlines()), 1, done.err)
        self.assertNotIn("Traceback", done.err)

    def test_a_request_outside_its_grammar_writes_nothing(self):
        self.told("acme-vm", "no")
        before = self.home.tree()
        for words in (("../acme", *self.began(), "no"), ("a" * 65, *self.began(), "no"),
                      *(("acme-vm", seconds, "yes") for seconds in ("nan", "-1", "1.5", "1e3"))):
            with self.subTest(words=words):
                done = self.ak("--copied", *words)
                self.assertNotEqual(done.code, 0, done.out)
                self.assertEqual(self.home.tree(), before)


if __name__ == "__main__":
    unittest.main()
