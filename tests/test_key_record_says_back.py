"""A record may say `back`: `ak standby --copied HOST WALL SINCE BOOT back` keeps it as one saying
`yes` or `no` is kept, the word `back` in it; `ak standby --takers` names its machine, which takes
over as one saying `yes` does; and `ak standby` lists it in the line it gives one saying `yes`, and
says more after it: that home goes back to that machine once it is steady; its help names `back`
among the words `--copied` takes.  Any other word is refused as misuse, exit 2, and leaves the
record byte for byte.  Black-box, through tests/fixtures/akbin.py, with the home's clocks from
AK_NOW (`wall seconds-since-boot boot`).
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

RECORD = ".agentkit/tmp/copies/acme-vm"      # the home's record of the machine acme-vm
STAMP = "1789000000 50000 acme-boot-1"      # the home's clocks a pass was handed, and now


class ARecordSaysBack(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.home.env["AK_NOW"] = STAMP

    def ak(self, *words):
        return self.home.ak("standby", *words)

    def told(self, word):
        """acme-vm's request, as a pass makes it, saying `word`."""
        return self.ak("--copied", "acme-vm", *STAMP.split(), word)

    def listed(self):
        """The one line `ak standby` names acme-vm in, ending well."""
        said = self.ak()
        self.assertEqual(said.code, 0, said.out + said.err)
        [line] = [line for line in said.out.splitlines() if "acme-vm" in line]
        return line

    def test_a_record_saying_back_is_kept_and_takes_over(self):
        done = self.told("back")
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual((self.home.path / RECORD).read_bytes(), f"{STAMP}\nback\n".encode())
        takers = self.ak("--takers")
        self.assertEqual((takers.code, takers.out), (0, "acme-vm\n"), takers.err)

    def test_its_line_is_one_saying_yes_and_more(self):
        self.assertEqual(self.told("back").code, 0)
        back = self.listed()
        self.assertEqual(self.told("yes").code, 0)
        yes = self.listed()
        self.assertTrue(back.startswith(yes) and len(back) > len(yes), (back, yes))

    def test_the_help_names_back_among_the_words_copied_takes(self):
        said = self.ak("--help")
        self.assertEqual(said.code, 0, said.err)
        self.assertIn("  ak standby --copied HOST WALL SINCE BOOT yes|no|back\n", said.out)

    def test_any_other_word_is_refused_and_leaves_the_record(self):
        self.assertEqual(self.told("back").code, 0)
        held = (self.home.path / RECORD).read_bytes()
        done = self.told("maybe")
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertEqual((self.home.path / RECORD).read_bytes(), held)


if __name__ == "__main__":
    unittest.main()
