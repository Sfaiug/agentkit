"""The lists `+ add a subscription` opens name what Enter does on each choice.

The owner (27 Oct 2026): "everywhere enter is for like opening, new page and stuff like that,
and space should be select / unselect".  `+ add a subscription`'s first list says `⏎ add` on
every row, OpenCode's `another provider` too (owner, 10 Nov 2026: "dependign on the provider, it
either says add or open. Fix this."); in the list that harness opens Enter is
`⏎ log in` on a provider not logged in to, `⏎ open` on a model and `⏎ add` on an effort, and
Space there opens nothing.  Black-box: `AK_BIN`'s menu in a terminal (tests/fixtures/akterm.py),
its harnesses faked (tests/fixtures/fakeadapter.py), the fake OpenCode listing MiMo, paid for,
and Zeta Cloud with no login; judged by what the terminal shows, NO_COLOR.  This test fails
against `/bin/false`.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_lists_space_marks_enter_picks import MAIN_KEYS, key_line, lines

KEYS = "  ↑↓←→ move   ⏎ {}   esc back"
# before the fake itself: what OpenCode lists, MiMo paid for and Zeta Cloud to log in to
OPENCODE = """case "$1" in
  providers) printf 'mimo\\tMiMo\\tpayg\\nzeta\\tZeta Cloud\\t\\n'; exit 0 ;;
  models) printf 'mimo/mimo-v2.6-pro\\tMiMo V2.6 Pro\\tnone high\\n'; exit 0 ;;
esac
"""


def downs_to_opencode(term):
    """How many rows below the first, where the highlight starts, `+ add a subscription`'s first
    list has OpenCode's `another provider`, its last: its rows are two cells in, under their
    companies' names, which the keys pass over."""
    shown = lines(term.wait(lambda screen: "  another provider" in lines(screen)
                            and key_line(screen) == KEYS.format("add")))
    return sum(line[:2] in ("  ", "› ") for line in shown[2:shown.index("  another provider")])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ListsNameWhatEnterDoes(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakes = fakeadapter.install(self.home, claude="pass", codex="pass", opencode="pass")
        fakes["opencode"].script.write_text(fakes["opencode"].script.read_text().replace(
            "#!/bin/sh\n", "#!/bin/sh\n" + OPENCODE, 1))
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"})
        now = time.time()
        week = {"meters": [{"name": "weekly", "used": 40, "window_secs": 604800}], "error": None}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {
            "anthropic": week, "openai": week}})
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen) and "ChatGPT" in screen)

    def on(self, row, enter):
        """The screen once the highlight is on the line that starts `row` and the key line
        names Enter as `enter`."""
        return self.term.wait(lambda screen: any(line.startswith(f"› {row}")
                                                 for line in lines(screen))
                              and key_line(screen) == KEYS.format(enter))

    def test_add_a_subscription_names_add_open_and_log_in(self):
        self.term.keys("c")
        self.term.wait("› Fable 5.1")
        for _ in range(3):                            # past 6 Astra and `Models`
            self.term.keys("Down")
        self.term.wait("› Subscriptions")
        self.term.keys("Enter")
        self.term.wait("+ add a subscription")
        self.term.keys("Down", "Down")                # past ChatGPT
        self.term.wait(KEYS.format("open"))
        self.term.keys("Enter")
        self.on("Claude II", "add")                   # another subscription
        self.term.keys(*["Down"] * downs_to_opencode(self.term))
        self.on("another provider", "add")            # a harness that lists providers
        self.term.keys("Enter")
        self.on("  MiMo V2.6 Pro", "open")
        self.term.keys("Space", "Down")               # Space first: had it opened, Down moves
        shown = self.on("  Zeta Cloud", "log in")   # among the efforts
        self.assertNotIn("  effort", lines(shown))
        self.term.keys("Up", "Enter")
        shown = self.on("  none", "add")
        self.assertIn("  effort", lines(shown))


if __name__ == "__main__":
    unittest.main()
