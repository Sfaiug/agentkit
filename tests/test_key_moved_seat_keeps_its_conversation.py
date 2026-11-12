"""A seat moved on `c` onto a new conversation keeps the one it left for its done check: the
owner's words there still owe a check, and the check reads them, under the account and directory
they were written under.

A Claude seat on the named Anthropic account `work` holds a transcript where the owner asks for
a retry button and then a receipt email; its plan holds the button alone, every line done.  The
owner moves it to Grok, another harness and provider, on xAI's named account `night`: a restart
onto a new conversation, which holds nothing of the owner's.  The seat does not read done, and
`ak orch check` names the email, quoting the owner.  A move whose restart fails leaves the
record's `left` as it was.  Black-box: `AK_BIN`, as the popup over the seat, its pane keeping
each line typed into it, as tests/test_key_seat_switches_in_place.py drives it, with fake
harnesses (tests/fixtures/fakeadapter.py); fails against `/bin/false`.
"""

import json
import re
import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SEAT = "acme"
BEFORE = "5b8e2d14-7c3a-4f69-9e1d-2a6c8f0b4d37"
FIRST = "Add a retry button to the upload page."
SECOND = "Also email me a receipt after every upload."
PLANNED = "The upload page has a retry button"
GAP = {"sh": f"{shlex.quote(AK)} hand-in finding \"$(grep -rlF -- {shlex.quote(SECOND)} . | "
             f"head -n 1):1\" 'no receipt email' 'the owner asked for it' "
             f"--quote {shlex.quote(SECOND)}",
       "final": "Checked.", "hand_in": [["done"]]}
CLEARED = [{"harness": "claude", "conversation": "e0c4a1b7-6d2f-4b8e-9a35-7f1c2d8e4b60",
            "account": "work"}]
KEYS = "  ↑↓←→ move   ␣ mark   r recommended   esc back"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def rows(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(rows(screen)) if line), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MovedSeatKeepsItsConversation(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.fakes = fakeadapter.install(home, claude="pass", grokbuild="pass")
        akconfig.write(home, ["opus", "grok"], workers=["opus"], providers={
            "anthropic": {"mode": "subscription", "accounts": ["work"]},
            "xai": {"mode": "subscription", "accounts": ["night"]}},
            extra='[done_check]\nmodel = "opus"')
        self.seat = seat = Seat(home, SEAT, model="opus", record={
            "conversation": BEFORE, "account": "work", "left": CLEARED})
        self.path = home.path / ".agentkit" / "state" / f"session-{SEAT}.json"
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        turns = []
        for text in (FIRST, SECOND):
            turns += [{"type": "user", "message": {"role": "user", "content": text}},
                      {"type": "assistant", "message": {"role": "assistant", "content": [
                          {"type": "text", "text": "Done."}]}}]
        home.write(f".claude-work/projects/{folder}/{BEFORE}.jsonl", "".join(
            json.dumps({**turn, "timestamp": f"2026-11-05T10:{n:02d}:00Z"}) + "\n"
            for n, turn in enumerate(turns)))
        home.write(f".agentkit/state/plan-{SEAT}.md", f"- [x] {PLANNED} · check: `true` · acme · "
                                                      "written 2026-11-05 10:05 · done 0123456789ab\n")
        self.term = Terminal(home, "attach", "--overlay", size=(100, 30),
                             env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", self.term.pane, "sleep 86400",
                        server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: key_line(screen) == KEYS and "› Opus 5.5" in screen)

    def record(self):
        return json.loads(self.path.read_text())

    def move(self):
        """Grok's orchestrator mark, and yes to the restart it asks for."""
        self.term.keys("Down", "Space")
        self.term.wait(lambda screen: any(row.startswith(f"  Restart {SEAT} on ")
                                          for row in rows(screen)) and "  × Move" in rows(screen))
        self.term.keys("Down", "Enter")

    def test_the_conversation_a_move_leaves_owes_a_check_that_finds_the_gap(self):
        self.move()
        self.term.wait(lambda _: self.record()["orchestrator"] == "grok"
                       and self.record()["conversation"] != BEFORE)
        why = self.home.ak("orch", "why", SEAT)
        self.assertEqual(why.code, 0, why.out + why.err)
        self.assertNotEqual(why.out.splitlines()[0], f"{SEAT}  done", why.out)
        self.fakes["claude"].behave(GAP)
        done = self.home.ak("orch", "check", SEAT)
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(SECOND, done.out)

    def test_a_move_whose_restart_fails_leaves_left_as_it_was(self):
        grok = self.fakes["grokbuild"]
        grok.answer("interactive", "", 1)
        self.move()
        self.term.wait(lambda screen: grok.calls("interactive") and key_line(screen) == KEYS)
        record = self.record()
        self.assertEqual((record["orchestrator"], record["left"]), ("opus", CLEARED))


if __name__ == "__main__":
    unittest.main()
