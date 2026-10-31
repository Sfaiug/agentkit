"""A seat's project whose `alive:` has failed for 5 minutes pages the owner once, with the
check's last line; a checkout no seat is filed under is never checked.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each
tick in the box `home.tick()` builds, on projects from gitrig.py, seats from akseat.py and the
webhook of sink.py.  Five minutes are not waited out: the first failing read is written where ak
keeps it, state/alive.json, five minutes back.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig
from fixtures.sink import Sink

DOWN = 'touch "$HOME/checked"; echo probing; echo 502 from acme.test; false'


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class ProjectDown(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(Home())
        config = self.home.path / ".agentkit" / "config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        self.home.env["AGENTKIT_DISCORD_USER_ID"] = "42"
        self.sink = self.enterContext(Sink(self.home))

    def project(self, name, check, seat=True):
        """A checkout declaring `check` as its `alive:`, a seat filed under it unless not `seat`."""
        rig = Rig(self.home, name, files={"AGENTS.md": f"---\nalive: {check}\n---\n"})
        if seat:
            Seat(self.home, f"fix-{name}", cwd=rig.path, record={"repo": str(rig.path)})
        return rig.path

    def tick(self):
        """One tick; every card the owner has been sent."""
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        return [request.json["content"] for request in self.sink.requests
                if request.method == "POST"]

    def test_down(self):
        repo = self.project("acme", DOWN)
        since = int(time.time()) - 300
        self.home.write(".agentkit/state/alive.json", {str(repo): since})
        card = f"🔴 acme is down since <t:{since}:t> · 502 from acme.test <@42>"
        self.assertEqual(self.tick(), [card])
        self.assertEqual(self.tick(), [card])

    def test_a_card_carries_the_beginning_of_the_last_line(self):
        # Long, padded, or after a progress meter's carriage return, it shows from its start.
        long = self.project("acme", "printf 'probing\\rCAUSE: db refused %05000d\\n\\n' 0; false")
        meter = self.project("acme-meter", "printf '%05000d\\rCAUSE: db refused\\n' 0; false")
        padded = self.project("acme-padded",
                              "printf 'probing\\nCAUSE: db refused%5000s\\n' ''; false")
        since = int(time.time()) - 300
        self.home.write(".agentkit/state/alive.json",
                        {str(repo): since for repo in (long, meter, padded)})
        down = f"is down since <t:{since}:t> ·"
        self.assertCountEqual(self.tick(), [f"🔴 acme {down} CAUSE: db refused {'0' * 182} <@42>",
                                            f"🔴 acme-meter {down} CAUSE: db refused <@42>",
                                            f"🔴 acme-padded {down} CAUSE: db refused <@42>"])

    def test_no_seat(self):
        self.project("acme", "true")
        unfiled = self.project("acme-old", DOWN, seat=False)
        self.home.write(".agentkit/state/alive.json", {str(unfiled): int(time.time()) - 300})
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.tick(), [])
        self.assertFalse((self.home.path / "checked").exists())


if __name__ == "__main__":
    unittest.main()
