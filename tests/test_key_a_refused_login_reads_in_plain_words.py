"""A move on `c` that no login passes reads under the rows in one line of plain words: the model
by the name every screen gives it, the subscription by the label `c` lists it under, and that it
is signed out -- never the adapter's own line, with its file path, variable and another
program's command, which goes whole to the tick's log for whoever debugs it.

The owner (12 Nov 2026), of the adapter's line on that screen: "weird output … Not user
friendly."  Black-box: `AK_BIN`, as the popup over a seat, its harnesses fakes whose `auth`
answers no; fails against `/bin/false`."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SEAT = "acme-fix"
KEYS = "  ↑↓←→ move   ␣ mark   r your runs   esc back"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def rows(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(rows(screen)) if line), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ARefusedLoginReadsInPlainWords(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.fakes = fakeadapter.install(home, claude="pass", codex="pass")
        self.path = home.path / ".agentkit" / "state" / f"session-{SEAT}.json"

    def said_no(self, harness):
        """The line `harness`'s `auth` answers no with, a path, a variable and a command in it."""
        line = (f"{harness}: no OAuth credentials in {self.home.path}/.{harness}/.credentials.json"
                " and no CLAUDE_CODE_OAUTH_TOKEN; run /login")
        self.fakes[harness].answer("auth", line, 1)
        return line

    def open_c(self):
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: key_line(screen) == KEYS and "› Opus 5.5" in screen)
        return term

    def refused(self, line, plain):
        """Its orchestrator mark one row down refused in `plain` words, none of `line`'s, which
        the log holds whole; the seat left as it was."""
        term, before = self.open_c(), self.path.read_bytes()
        term.keys("Down", "Space")
        screen = term.wait(lambda screen: f"  {plain}" in rows(screen))
        for part in (str(self.home.path), ".credentials.json", "CLAUDE_CODE_OAUTH_TOKEN",
                     "run /login"):
            self.assertNotIn(part, screen)
        self.assertIn(line, (self.home.path / ".agentkit/tmp/watch.log").read_text())
        self.assertEqual(self.path.read_bytes(), before)

    def test_a_provider_with_one_subscription_is_named_as_c_names_it(self):
        line = self.said_no("codex")
        akconfig.write(self.home, ["opus", "astra"], workers=["opus"])
        Seat(self.home, SEAT, model="opus", record={"reviewers": ["astra"]})
        self.refused(line, "6 Astra: ChatGPT is signed out")     # another provider's

    def test_a_login_its_provider_lists_no_more_is_named_as_its_one_subscription(self):
        line = self.said_no("claude")
        akconfig.write(self.home, ["opus", "fable"], workers=["opus"])     # no `accounts`
        seat = Seat(self.home, SEAT, model="opus", record={"account": "second"})
        self.home.tmux("new-window", "-d", "-t", f"={SEAT}:", "sleep 86400")
        self.home.tmux("kill-pane", "-t", seat.pane)       # gone: the move restarts it
        self.refused(line, "Fable 5.1: Claude is signed out")

    def test_one_of_several_subscriptions_is_named_by_its_place(self):
        line = self.said_no("claude")
        akconfig.write(self.home, ["opus", "fable"], workers=["opus"],
                       providers={"anthropic": {"accounts": ["default", "second"]}})
        seat = Seat(self.home, SEAT, model="opus", record={"account": "second"})
        self.home.tmux("new-window", "-d", "-t", f"={SEAT}:", "sleep 86400")
        self.home.tmux("kill-pane", "-t", seat.pane)       # gone: the move restarts it
        self.refused(line, "Fable 5.1: Claude II is signed out")


if __name__ == "__main__":
    unittest.main()
