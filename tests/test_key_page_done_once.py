"""A seat whose plan is all done pages `✅ Done · <seat>` once, and again only for new work.

A done page tells the owner the whole finished job is ready to look at, once.  The seat going
to work and back to its prompt with nothing new in its plan is the same job and pages nothing
more; a line it finishes since is new work and pages once more, the card then covering both.
The seat's word reads `done`, with the finished line as its reason.  Black-box: the program
`AK_BIN` names runs boxed ticks from outside through tests/fixtures/akbin.py, before a seat of
tests/fixtures/akseat.py on the fixture harness tests/fixtures/adapters/echo.toml, paging
tests/fixtures/sink.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.sink import Sink
from fixtures import akconfig

ADAPTERS = Path(__file__).resolve().parent / "fixtures" / "adapters"
PROMPT = "shipped it\n\n❯ \n? for shortcuts\n"
WORKING = "thinking...\nesc to interrupt\n\n❯ \n? for shortcuts\n"
PAGE = "✅ Done · acme"


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class DonePagesOncePerCompletion(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.sink = Sink(self.home)
        self.addCleanup(self.sink.close)
        self.home.env["AGENTKIT_ADAPTER_DIR"] = str(ADAPTERS)
        akconfig.write(self.home, {"echo": {"harness": "echo", "model": "echo-1"}})

    def state(self, name):
        return json.loads((self.home.path / ".agentkit/state" / name).read_text())

    def plan(self, *done):
        self.home.write(".agentkit/state/plan-acme.md", "".join(f"- [x] {line}\n"
                                                                for line in done))

    def tick(self, seat, screen):
        seat.show(screen)
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.err)
        return self.sink.pages()

    def test_a_finished_plan_pages_once_and_new_finished_work_pages_once_more(self):
        self.plan("ship the release")
        seat = Seat(self.home, "acme", model="echo", screen=PROMPT)
        self.assertEqual(self.tick(seat, PROMPT), [PAGE])
        card = self.state("card-acme.json")
        self.assertEqual({key: card.get(key) for key in ("word", "sent", "closed", "completed")},
                         {"word": "done", "sent": True, "closed": "Done",
                          "completed": {"created": seat.record["created"],
                                        "outcomes": [["", "ship the release"]]}})
        word = self.state("seat-acme.json")
        self.assertEqual((word["word"], word["reason"]), ("done", "ship the release"))

        self.assertEqual(self.tick(seat, WORKING), [PAGE])
        self.assertEqual(self.tick(seat, PROMPT), [PAGE])

        self.plan("ship the release", "fix the docs")
        self.assertEqual(self.tick(seat, WORKING), [PAGE])
        self.assertEqual(self.tick(seat, PROMPT), [PAGE, PAGE])
        self.assertEqual(self.state("card-acme.json")["completed"]["outcomes"],
                         [["", "fix the docs"], ["", "ship the release"]])


if __name__ == "__main__":
    unittest.main()
