"""After a tick lands a version, a fresh Python compiles none of the modules under agentkit/.

Black-box: a tick of the live copy in tests/fixtures/akinstall.py lands each commit.  What the
Python the program runs on would do is asked of its own loader, which reads bytecode and compiles
only where that will not load, and never runs the module.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akinstall import Install

COMPILED = """
import importlib.machinery, pathlib, sys
sys.addaudithook(lambda event, args: event == "compile" and print(args[1]))
for source in pathlib.Path(sys.argv[1]).rglob("*.py"):
    importlib.machinery.SourceFileLoader(source.stem, str(source)).get_code(source.stem)
"""


class ALandingLeavesItsBytecodeReady(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.install = Install(self.home)

    def ready(self, name="notes"):
        tip = self.install.advance(name)
        done = self.home.run(self.install.ak, "watch")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.install.head(), tip)
        asked = self.home.run("python3", "-B", "-c", COMPILED, str(self.install.path / "agentkit"))
        self.assertEqual((asked.code, asked.out), (0, ""), asked.err)

    def test_a_landing_keeping_the_modules_times(self):
        self.ready()

    def test_a_landing_with_code(self):
        self.ready("agentkit/config.py")

    def test_a_landing_under_a_cache_prefix(self):
        self.home.env["PYTHONPYCACHEPREFIX"] = str(self.home.root / "pycache")
        self.ready("agentkit/config.py")


if __name__ == "__main__":
    unittest.main()
