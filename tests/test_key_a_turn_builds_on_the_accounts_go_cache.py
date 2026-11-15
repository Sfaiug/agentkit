"""An `ak worker` turn's Go reads the account's build cache, and what it writes there stays the
turn's.

A turn whose cache was empty compiled the standard library and every package from nothing: with
about 40 runs open on a Go tree, their turns' cold builds asked for more CPU than the host had,
and every project's changes waited hours (15 Nov 2026).  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, with a scripted harness from fakeadapter.py
whose `sh` step reads a file the account's cache holds through `$GOCACHE` and writes one beside
it; the class skips where bubblewrap cannot box one.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home, boxable


@unittest.skipUnless(boxable(), "no bwrap able to box a turn here")
class ATurnBuildsOnTheAccountsGoCache(unittest.TestCase):
    def test_the_turn_reads_the_accounts_cache_and_leaves_it_as_it_was(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {"beta": {"harness": "acme", "model": "beta-1", "effort": "low"}})
        fake = fakeadapter.install(home, acme="pass")["acme"]
        # Where Go keeps the cache of a HOME, and an account's environment names no other.
        cache = home.path / ".cache" / "go-build"
        cache.mkdir(parents=True)
        (cache / "held").write_text("account\n")
        ws = home.path / "code" / "widgets"
        ws.mkdir(parents=True)
        fake.behave({**fakeadapter.PASS,
                     "sh": 'cat "$GOCACHE/held" > read; echo turn > "$GOCACHE/own"; echo $? > wrote'})
        done = home.ak("worker", "beta", str(home.write("read.md", "Read the cache.\n")),
                       "--workspace", str(ws), "--out", str(home.path / "out"))
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(((ws / "read").read_text(), (ws / "wrote").read_text()),
                         ("account\n", "0\n"))
        self.assertEqual(sorted(path.name for path in cache.iterdir()), ["held"])


if __name__ == "__main__":
    unittest.main()
