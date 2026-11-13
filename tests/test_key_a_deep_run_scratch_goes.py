"""A dead maker's scratch in a run's folder goes at the next `ak run gc` however deep it is:
deeper than Python calls nest, and than the files the collection may hold open.

Black-box: `AK_BIN` collects a Home (tests/fixtures/akbin.py) holding the scratch the way ak
leaves it, its mark naming a process long gone, with a /tmp of its own (`home.ak(boxed=True)`),
under `ulimit -n 256`.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, boxable, Home
from fixtures.garbage import ROOM, run

DEPTH = 1100     # past Python's 1,000 nested calls and a systemd unit's 1,024 open files


@unittest.skipUnless(boxable(), "no bwrap able to box a collection here")
class ADeepRunScratchGoes(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(Home())
        self.folder = run(self.home, "acme-deep", 1, state="pass")
        self.scratch = self.home.write(".agentkit/runs/acme-deep/tmp-left/.ak-scratch",
                                       {"pid": 99999999, "process_identity": None}).parent
        self.chain = [self.scratch]
        for _ in range(DEPTH):
            self.chain.append(self.chain[-1] / "d")
            self.chain[-1].mkdir()
        (self.chain[-1] / "payload").write_text("scratch\n")
        self.addCleanup(self.unwind)

    def unwind(self):
        """What a failed collection left, deepest first: no recursive removal reaches it."""
        (self.chain[-1] / "payload").unlink(missing_ok=True)
        for folder in reversed(self.chain[1:]):
            if folder.exists():
                folder.rmdir()

    def test_it_goes_whole_and_the_run_stays(self):
        done = self.home.run("sh", "-c", 'ulimit -n 256 && exec "$@"', "sh",
                             *self.home.box(), AK, "run", "gc", env=ROOM)
        self.assertEqual(done.code, 0, done.err)
        self.assertIn(f"gc: remove run-scratch {self.scratch}", done.out)
        self.assertFalse(self.scratch.exists())
        self.assertTrue((self.folder / "run.json").is_file())


if __name__ == "__main__":
    unittest.main()
