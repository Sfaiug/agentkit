"""An `ak worker` turn builds Go, though its HOME, where Go keeps its build cache, is read-only.

A turn's box lets Go write the account's build cache, so a done-when `go test` the executor runs
compiles instead of failing on a read-only cache, and what it compiled serves the next turn, check
or proof instead of being compiled again.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, with a scripted harness from fakeadapter.py whose
`sh` step builds a Go package inside the turn; the class skips where bubblewrap cannot box one.
"""

import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REPO, Home, boxable


@unittest.skipUnless(boxable(), "no bwrap able to box a turn here")
class ATurnBuildsGo(unittest.TestCase):
    def test_a_go_build_in_a_turn_exits_0_and_fills_the_accounts_cache(self):
        # The Home outside the turn's temporary places, so the turn sees it read-only, as it
        # sees a real HOME, not as a skeleton of its own places in an empty /tmp.
        outside = tempfile.TemporaryDirectory(prefix=".ak-test-key-go-", dir=REPO)
        self.addCleanup(outside.cleanup)
        before, tempfile.tempdir = tempfile.tempdir, outside.name
        try:
            home = Home()
        finally:
            tempfile.tempdir = before
        self.addCleanup(home.close)
        akconfig.write(home, {"beta": {"harness": "acme", "model": "beta-1", "effort": "low"}})
        fake = fakeadapter.install(home, acme="pass")["acme"]
        ws = home.path / "code" / "widgets"
        (ws / "p").mkdir(parents=True)
        (ws / "go.mod").write_text("module acme\n\ngo 1.21\n")
        (ws / "p" / "p.go").write_text("package p\n\nfunc F() int { return 1 }\n")
        fake.behave({**fakeadapter.PASS, "sh": "go build ./p 2> built.err; echo $? > built"})
        done = home.ak("worker", "beta", str(home.write("build.md", "Build p.\n")),
                       "--workspace", str(ws), "--out", str(home.path / "out"))
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual((ws / "built").read_text(), "0\n", (ws / "built.err").read_text())
        # Go keeps each entry in one of its cache's 256 folders, here where an empty environment
        # has it keep the account's.
        self.assertTrue(any((home.path / ".cache" / "go-build").glob("??/*")))


if __name__ == "__main__":
    unittest.main()
