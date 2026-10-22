"""A watch preview leaves a fresh HOME unchanged, including its run-record cache.

Black-box: the program `AK_BIN` names runs through tests/fixtures/akbin.py.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home


class WatchDryRun(unittest.TestCase):
    def test_a_preview_writes_nothing_in_a_fresh_home(self):
        with Home() as home:
            akconfig.write(home, ["opus", "astra"])
            before = home.tree()
            done = home.ak("watch", "--dry-run", env={"PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual(home.tree(), before)


if __name__ == "__main__":
    unittest.main()
