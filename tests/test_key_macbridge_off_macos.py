"""`ak macbridge` off macOS refuses, points at `ak fetch`, and touches nothing.

The bridge carries files dropped on a Mac's terminal to the host the seats run on; on that host
itself it has nothing to bridge, and a model that runs it there must be told which verb fetches
instead, not left with a bridge that reaches for ssh or a lock under HOME.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REFUSED, Home

REFUSAL = "ak macbridge: ak macbridge runs on macOS; use ak fetch on this host\n"


@unittest.skipIf(sys.platform == "darwin", "the bridge runs here")
class OffMacos(unittest.TestCase):
    def test_every_form_of_the_verb_is_refused_and_names_ak_fetch(self):
        with Home() as home:
            before = home.tree()
            for args in ([], ["--reader"], ["--lock-fd", "3"], ["acme"]):
                with self.subTest(args=args):
                    done = home.ak("macbridge", *args)
                    self.assertEqual(done.code, 2, done.out)
                    self.assertEqual(done.err, REFUSAL)
            self.assertEqual(home.tree(), before)
            for tool in REFUSED:
                self.assertEqual(home.calls(tool), [], tool)


if __name__ == "__main__":
    unittest.main()
