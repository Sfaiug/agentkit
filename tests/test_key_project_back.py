"""A seat's project whose down card is out sends one card, mentioning nobody, at the first tick
its `alive:` passes again.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each
tick in the box `home.tick()` builds, on a project from gitrig.py, a seat from akseat.py and the
webhook of sink.py.  Five minutes are not waited out: the first failing read is written where ak
keeps it, state/alive.json, 45 minutes back.
"""

from pathlib import Path
import re
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig
from fixtures.sink import Sink


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class ProjectBack(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(Home())
        config = self.home.path / ".agentkit" / "config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        self.home.env["AGENTKIT_DISCORD_USER_ID"] = "42"
        self.sink = self.enterContext(Sink(self.home))

    def tick(self):
        """One tick; the cards it sent."""
        before = len(self.sink.requests)
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        return [request.json for request in self.sink.requests[before:]
                if request.method == "POST"]

    def test_back(self):
        rig = Rig(self.home, "acme", files={"AGENTS.md": '---\nalive: test -e "$HOME/up"\n---\n'})
        Seat(self.home, "fix-acme", cwd=rig.path, record={"repo": str(rig.path)})
        since = int(time.time()) - 45 * 60
        self.home.write(".agentkit/state/alive.json", {str(rig.path): since})
        down, = self.tick()
        self.assertTrue(down["content"].startswith(f"🔴 acme is down since <t:{since}:t>"))
        (self.home.path / "up").touch()
        before = int(time.time())
        back, = self.tick()
        at, minutes = re.fullmatch(r"acme is back since <t:(\d+):t>, after (\d+) min",
                                   back["content"]).groups()
        self.assertLessEqual(before, int(at))
        self.assertEqual(int(minutes), (int(at) - since) // 60)
        self.assertEqual(back["allowed_mentions"], {"parse": []})
        self.assertEqual(self.tick(), [])


if __name__ == "__main__":
    unittest.main()
