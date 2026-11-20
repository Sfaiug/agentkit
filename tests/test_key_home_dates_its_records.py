"""A home hands a pass a stamp of its own, `ak standby --began`: its clocks now as one line, `wall
seconds-since-boot boot`, each clock as Python's float prints it, and exits 0, writing nothing; a
stamp whose words a request could not hand back, a boot beginning with a dash or a clock printed
with an exponent, it prints nothing of, says why in one line and exits 1.  `ak standby --copied
HOST WALL SINCE BOOT yes|no` keeps HOST's record as those three words, written as handed, and the
last: dated by the stamp whatever the home's clocks say when the request arrives, so `ak standby`
there tells the copy's age from it.  Another host's record is left byte for byte, nothing else
lands among the records nor in a standby's own folder, and words outside the grammar write
nothing.  Black-box, through tests/fixtures/akbin.py, with the home's clocks from AK_NOW.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

RECORDS = ".agentkit/tmp/copies"      # the home's records of the machines that copy it
OWN = ".agentkit/tmp/standby"       # a standby's own folder, which makes a client one
BEGAN = "1789000000 50000 acme-boot-1"      # the home's clocks when a pass began
STAMP = "1789000000.0 50000.0 acme-boot-1"      # as --began prints them
LATER = "1789000300 50300 acme-boot-1"     # five minutes on
# The home's clocks when a request arrives: an hour late, the wall a day back, after a reboot.
ARRIVED = ("1789003600 53600 acme-boot-1", "1788913600 53600 acme-boot-1",
           "1789003600 3600 acme-boot-2")


def minutes(count):
    """An age of `count` minutes, a word of its own."""
    return rf"(?<![\w-]){count}m(?![\w-])"


class AHomeDatesItsRecords(unittest.TestCase):
    def ak(self, home, *args, now=BEGAN):
        home.env["AK_NOW"] = now
        return home.ak("standby", *args)

    def ended(self, home, *args, now=BEGAN):
        """What `ak standby` printed, ending well."""
        done = self.ak(home, *args, now=now)
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out

    def listed(self, home):
        """The line `ak standby` on the home says of acme-vm, five minutes after BEGAN."""
        [line] = [line for line in self.ended(home, now=LATER).splitlines() if "acme-vm" in line]
        return line

    def test_a_home_prints_its_stamp_and_writes_nothing(self):
        for now, printed in ((BEGAN, STAMP),
                             ("1789000000.250 50000.5 acme-boot-1",
                              "1789000000.25 50000.5 acme-boot-1")):
            with self.subTest(now=now), Home() as home:
                before = home.tree()
                done = self.ak(home, "--began", now=now)
                self.assertEqual((done.code, done.out, done.err), (0, f"{printed}\n", ""))
                self.assertEqual(home.tree(), before)

    def test_a_stamp_no_request_could_hand_back_is_not_printed(self):
        for now in ("1789000000 50000 -acme-boot-1", "1789000000 0.00001 acme-boot-1"):
            with self.subTest(now=now), Home() as home:
                before = home.tree()
                done = self.ak(home, "--began", now=now)
                self.assertEqual((done.code, done.out), (1, ""), done.err)
                self.assertEqual(len(done.err.splitlines()), 1, done.err)
                self.assertNotIn("Traceback", done.err)
                self.assertEqual(home.tree(), before)

    def test_a_record_is_the_stamp_handed_back_whenever_it_arrives(self):
        for arrived, takes in (*((now, "no") for now in ARRIVED), (ARRIVED[0], "yes")):
            with self.subTest(arrived=arrived, takes=takes), Home() as home:
                line = self.ended(home, "--began").removesuffix("\n")
                self.ended(home, "--copied", "acme-vm", *line.split(" "), takes, now=arrived)
                self.assertEqual((home.path / RECORDS / "acme-vm").read_bytes(),
                                 f"{line}\n{takes}\n".encode())
                listed = self.listed(home)
                self.assertRegex(listed, minutes(5))
                self.assertEqual("takes over" in listed, takes == "yes", listed)

    def test_a_record_handed_a_stamp_leaves_the_rest(self):
        with Home() as home:
            self.ended(home, "--copied", "acme-mac", "0", "yes")
            records = home.path / RECORDS
            record = (records / "acme-mac").read_bytes()
            self.ended(home, "--copied", "acme-vm", *STAMP.split(" "), "no", now=LATER)
            self.assertEqual((records / "acme-mac").read_bytes(), record)
            self.assertEqual(sorted(path.name for path in records.iterdir()),
                             ["acme-mac", "acme-vm"])
            self.assertNotIn(OWN, home.tree())

    def test_words_outside_the_grammar_write_no_record(self):
        for words in (("1789000000.0", "50000.0", "-acme-boot-1", "no"),
                      ("17890000a0.0", "50000.0", "acme-boot-1", "no"),
                      ("1789000000.0", "5" * 13, "acme-boot-1", "no"),
                      (*STAMP.split(" "), "no", "acme")):
            with self.subTest(words=words), Home() as home:
                before = home.tree()
                done = self.ak(home, "--copied", "acme-vm", *words)
                self.assertNotEqual(done.code, 0, done.out)
                self.assertEqual(home.tree(), before)

if __name__ == "__main__":
    unittest.main()
