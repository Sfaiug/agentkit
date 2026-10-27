"""A Codex seat ak cannot prove a conversation of its own comes back with no past, and says so
in plain words: its row on past sessions, highlighted, says it `starts a new Codex conversation`,
and reopening it says `it starts a new Codex conversation`.  Black-box: `AK_BIN` in a terminal
(tests/fixtures/akterm.py) and from outside (tests/fixtures/akbin.py)."""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

KEYS = "  ↑↓←→ move   ⏎ reopen   x remove   esc back"


def closed(home):
    """fix-api of acme on Codex, closed by the owner an hour ago, with no conversation of its own."""
    checkout = home.path / "code/acme"
    checkout.mkdir(parents=True)
    assert home.run("git", "init", "-q", str(checkout)).code == 0
    home.write(".agentkit/state/session-fix-api.json", {
        "orchestrator": "astra", "workers": ["astra"], "cwd": str(checkout),
        "repo": str(checkout), "created": int(time.time()) - 7200})
    home.write(".agentkit/state/seat-fix-api.json",
               {"stopped_at": time.time() - 3600, "closed_by_owner": True})
    return checkout


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NoConversationOfItsOwn(unittest.TestCase):
    def test_highlighted_on_past_sessions_it_says_it_starts_a_new_codex_conversation(self):
        with Home() as home:
            closed(home)
            menu = Terminal(home, size=(100, 30))
            menu.wait(lambda screen: "p past" in screen)
            menu.keys("p")
            screen = menu.wait(lambda screen: KEYS in screen and "fix-api" in screen
                               and screen.startswith("agentkit · past sessions"))
            shown = [line.rstrip() for line in screen.split("\n")]
            row = next(n for n, line in enumerate(shown) if line.startswith("› 1  fix-api "))
            self.assertEqual(shown[row + 1].strip(), "starts a new Codex conversation")

    def test_reopening_it_says_it_starts_a_new_codex_conversation(self):
        with Home() as home:
            checkout = closed(home)
            done = home.ak("orch", "fix-api", "--dry-run")
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(done.out.splitlines()[0],
                             f"orch: resuming fix-api on astra in {checkout} "
                             f"(it starts a new Codex conversation)")


if __name__ == "__main__":
    unittest.main()
