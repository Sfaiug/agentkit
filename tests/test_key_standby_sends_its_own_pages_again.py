"""A standby's pages are its own: a pass neither copies its home's nor deletes its own, and first
sends again, as a home's tick does, a page of its own the webhook did not take, whether its home
answers or not.  Black-box, through tests/fixtures/twohomes.py: `acme-vm` is `acme-mini`'s
standby, and its `ak update` puts back a move whose bin/ak cannot start, paging once, as on any
client (tests/test_key_a_client_move_that_cannot_start_is_put_back.py), while the webhook,
tests/fixtures/sink.py, answers 503.  Each retry is made due at once, as its wait passing leaves
it.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.sink import Sink
from fixtures.twohomes import Machines

OUTBOX = ".agentkit/state/notification-outbox"
# the commit moved to's bin/ak: it exits 19 for `--dry-run`, every other verb is the program's
FAILS = '#!/bin/sh\n[ "$1" != --dry-run ] || exit 19\nexec "$(dirname "$0")/program" "$@"\n'
HOMES = f"{OUTBOX}/{'0' * 64}.json"     # a page of the home's, due, which only the home sends


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AStandbySendsItsOwnPagesAgain(unittest.TestCase):
    def test_a_page_the_webhook_did_not_take_goes_out_on_a_later_pass(self):
        home, here = self.enterContext(Machines("acme-mini", "acme-vm"))
        self.addCleanup(home.answer)
        here.client_of(home)
        sink = self.enterContext(Sink(here))
        home.write(HOMES, {"id": "0" * 64, "session": None, "kind": "needs", "text": "home",
                           "payload": {"content": "home"}, "message": "home",
                           "created_at": time.time(), "sink": True, "status": "pending",
                           "attempts": 0, "next_attempt": 0, "happened": True})
        self.assertEqual(here.ak("standby", home.name, timeout=120).code, 0)
        self.assertFalse((here.path / HOMES).exists())
        first = here.install.head()
        ak = home.install.seed / "bin/ak"
        ak.rename(ak.with_name("program"))
        ak.write_text(FAILS)
        ak.chmod(0o755)
        moved = home.install.advance()
        home.install.git("fetch", "-q", "origin")
        home.install.git("merge", "-q", "--ff-only", moved)
        sink.script(503, 503)
        done = here.ak("update", timeout=120)
        self.assertNotEqual(done.code, 0, done.out + done.err)
        self.assertEqual(here.install.head(), first)
        event, = (here.path / OUTBOX).glob("*.json")

        def due():
            here.write(event.relative_to(here.path),
                       {**json.loads(event.read_text()), "next_attempt": 0})

        due()
        done = here.ak("standby", home.name, timeout=120)     # refused again, and kept
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(json.loads(event.read_text())["status"], "pending")
        due()
        home.silence()
        self.assertNotEqual(here.ak("standby", home.name, timeout=120).code, 0)
        self.assertEqual(json.loads(event.read_text())["status"], "delivered")
        page, *again = sink.pages()
        self.assertEqual(again, [page, page])
        for named in (first[:12], moved[:12]):
            self.assertIn(named, page)


if __name__ == "__main__":
    unittest.main()
