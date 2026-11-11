"""Codex 0.167.0's prompt reads as Codex means it: at `ultra` effort, on its `»` mark; beside a
model its status row names in two words, `GPT-6.1 Terra`; and under the startup warning a `-c`
override draws, as ak's launch makes, joined to its footer's key hints.

Read wrong, its empty prompt is a draft or no prompt at all, a draft reads as an empty prompt,
and a line ak types there is never delivered, so every later line waits behind it.  Each screen
is a capture of Codex 0.167.0 in tests/fixtures.  Black-box: `AK_BIN`, its seat's pane showing
those captures, as tests/test_key_codex_words.py reads a screen and
tests/test_key_codex_switches_in_place.py moves a seat; fails against `/bin/false`."""

import json
import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

FIELD = re.compile(r"^\s+(\w+):\s+(.*?)\s*$")
DECIDED = re.compile(r"^(\S+)\s+rule:\s+(\S+)$")
SEAT = "acme-fix"
KEYS = "  ↑↓←→ move   ␣ mark   r recommended   esc back"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
# Each screen with its composer's prompt mark as the capture draws it, its colours before it,
# so the pane shows what is typed there in that row.
MARKS = {"codex-ultra-pane.txt": "\x1b[1m\x1b[38;5;141m»",
         "codex-spaced-model-pane.txt": "\x1b[1m›"}


def key_line(screen):
    return next((line.rstrip() for line in reversed(screen.split("\n")) if line.strip()), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CodexReadsIts0167Prompt(unittest.TestCase):
    def why(self, home, seat, screen):
        """`ak orch why` with that screen in the seat: (first line, authority, rule, evidence)."""
        seat.show(screen)
        done = home.ak("orch", "why", seat.name)
        self.assertEqual(done.code, 0, done.err)
        first, *rest = done.out.splitlines() or [""]
        fields = dict(found.groups() for found in map(FIELD.match, rest) if found)
        decided = DECIDED.match(fields.get("authority", ""))
        self.assertIsNotNone(decided, done.out)
        return (first, *decided.groups(), fields.get("evidence"))

    def test_each_screen_reads_at_its_prompt_or_holding_its_draft(self):
        home = Home()
        self.addCleanup(home.close)
        seat = Seat(home, "acme", model="astra", screen="codex-prompt-pane.txt")
        for name in ("ultra", "spaced-model", "startup-warning"):
            with self.subTest(name):
                self.assertEqual(self.why(home, seat, f"codex-{name}-pane.txt")[:3],
                                 ("acme  idle", "screen", "prompt.suggestion"))
        self.assertEqual(self.why(home, seat, "codex-ultra-draft-pane.txt"),
                         ("acme  idle", "screen", "prompt.draft", "Fix the login redirect"))

    def test_a_move_in_place_is_typed_and_delivered(self):
        for screen, mark in MARKS.items():
            with self.subTest(screen):
                self.moved(screen, mark)

    def moved(self, screen, mark):
        """A seat on that screen moved to another Codex model of its login takes its `/model`
        line, and owes it no line once its composer reads empty again."""
        home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, codex="pass")
        akconfig.write(home, {"astra": {}, "luna": {"harness": "codex", "model": "gpt-5.6-luna"}})
        seat = Seat(home, SEAT, model="astra", screen=screen, composer=mark)
        term = Terminal(home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda shown: key_line(shown) == KEYS and "› GPT-6-Astra" in shown)
        term.keys("Down", "Space")     # the other Codex model's orchestrator mark
        self.assertEqual(seat.wait_lines(1), ["/model gpt-5.6-luna --reasoning=high"])
        state = home.path / ".agentkit" / "state" / f"seat-{SEAT}.json"
        deadline = time.monotonic() + 30
        while json.loads(state.read_text()).get("owed_lines"):
            self.assertLess(time.monotonic(), deadline, state.read_text())
            time.sleep(0.1)


if __name__ == "__main__":
    unittest.main()
