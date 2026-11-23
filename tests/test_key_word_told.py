"""The word a standby's pass that ends well tells its home, that the home's record of it says
after the home's stamp, is decided by the words of the standby's own records, whatever their
names, so in a case of two the one not named after the home decides: `back` where one reads as a
stamp and says `yes`; else `yes`, for one saying `back`, none, only `no`, or only records that
cannot be read.  Black-box, through tests/fixtures/twohomes.py, acme-vm the standby of acme-mini
as tests/test_key_standby_job_and_age.py builds one, each case its own machines; the key writes
acme-vm's records itself.  What came back is the pass's exit, read undecoded, and the bytes of
acme-mini's record of acme-vm.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from test_key_home_creates_a_lease import RECORDS
from test_key_standby_job_and_age import BEGAN, standby

STAMP = "1789000000 10000 acme-boot-1"      # what a record on acme-vm is dated by


def says(word):
    """A record dated by STAMP saying `word`."""
    return f"{STAMP}\n{word}\n"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AWordTold(unittest.TestCase):
    def told(self, word, records=None):
        """acme-vm keeping `records`, each by its name: its pass ends 0 and leaves acme-mini's
        record of it, acme-mini's stamp and `word`."""
        with standby() as (home, here):
            for name, held in (records or {}).items():
                here.write(RECORDS / name, held)
            done = here.ak("standby", home.name, raw=True)
            self.assertEqual(done.code, 0, done.err)
            record = (home.path / RECORDS / here.name).read_bytes()
        self.assertEqual(record, f"{BEGAN}\n{word}\n".encode())

    def test_no_record_tells_yes(self):
        self.told("yes")

    def test_a_record_saying_no_tells_yes(self):
        self.told("yes", {"acme-mini": says("no")})

    def test_a_record_of_one_line_that_is_no_stamp_tells_yes(self):
        self.told("yes", {"acme-mini": "yes\n"})

    def test_a_record_saying_yes_tells_back(self):
        self.told("back", {"acme-mini": says("yes")})

    def test_a_record_saying_yes_beside_one_saying_back_tells_back(self):
        self.told("back", {"acme-mini": says("back"), "acme-old": says("yes")})

    def test_a_record_saying_back_tells_yes(self):
        self.told("yes", {"acme-mini": says("back")})

    def test_a_record_saying_back_beside_one_saying_no_tells_yes(self):
        self.told("yes", {"acme-mini": says("no"), "acme-old": says("back")})


if __name__ == "__main__":
    unittest.main()
