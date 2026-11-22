"""`ak standby --takers` prints, one a line and in the order of their names, the name of each
machine whose record here reads as a stamp and says it takes over, and exits 0: none for a record
saying `no` or one that is no stamp, nothing at all where no record is kept.  Given a second word it
is refused as `ak standby`'s other misuse is, printing nothing.  Black-box, through
tests/fixtures/akbin.py, the records written as `ak standby --copied` keeps them.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

RECORDS = ".agentkit/tmp/copies"      # the home's records of the machines that copy it
STAMP = "1789000000 50000 acme-boot-1"      # the home's clocks a pass was handed


class AStandbyNamesItsTakers(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def takers(self, *words):
        return self.home.ak("standby", "--takers", *words)

    def test_each_record_saying_yes_is_named_in_the_order_of_their_names(self):
        for host, held in (("acme-b", f"{STAMP}\nyes\n"), ("acme-a", f"{STAMP}\nyes\n"),
                           ("acme-old", f"{STAMP}\nno\n"), ("acme-torn", "torn\n")):
            self.home.write(f"{RECORDS}/{host}", held)
        done = self.takers()
        self.assertEqual((done.code, done.out), (0, "acme-a\nacme-b\n"), done.err)

    def test_no_folder_of_records_names_none(self):
        self.assertFalse((self.home.path / RECORDS).exists())
        done = self.takers()
        self.assertEqual((done.code, done.out), (0, ""), done.err)

    def test_a_second_word_is_refused_as_any_other_misuse(self):
        misuse = self.home.ak("standby", "--began", "extra")
        self.assertNotEqual(misuse.code, 0, misuse.out + misuse.err)
        done = self.takers("extra")
        self.assertEqual((done.code, done.out), (misuse.code, ""), done.err)


if __name__ == "__main__":
    unittest.main()
