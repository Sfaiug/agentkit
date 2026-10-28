"""Esc in the list a harness opens under `+ add a subscription` goes back one list: to the first
list, that harness highlighted, and Esc there to Subscriptions; a model added through the
harness still lands on Subscriptions, as Ctrl-D from its models or efforts does.  The owner's rule: "the same back, forward and exit keys
everywhere" (docs/cli-design.md).  Black-box: `AK_BIN`'s menu in a terminal
(tests/fixtures/akterm.py), its harnesses faked (tests/fixtures/fakeadapter.py), the fake
OpenCode listing MiMo, paid for; judged by what the terminal shows, NO_COLOR.  This test fails
against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_lists_name_what_enter_does import KEYS, OPENCODE
from test_key_lists_space_marks_enter_picks import MAIN_KEYS, key_line, lines
from test_key_subscriptions_page import ADD, PAGE, title


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AddSubscriptionEscBackOneList(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakes = fakeadapter.install(self.home, claude="pass", codex="pass", opencode="pass")
        fakes["opencode"].script.write_text(fakes["opencode"].script.read_text().replace(
            "#!/bin/sh\n", "#!/bin/sh\n" + OPENCODE, 1))
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"})
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen))
        self.term.keys("c")
        self.term.wait("› Fable 5.1")
        for _ in range(3):                            # past GPT-6-Astra and `Models`
            self.term.keys("Down")
        self.term.wait("› Subscriptions")
        self.term.keys("Enter")
        self.term.wait("+ add a subscription")
        self.opencode()

    def opencode(self):
        """From Subscriptions, OpenCode's own list under `+ add a subscription`."""
        self.term.keys("Down", "Down")                # past ChatGPT
        self.term.wait(KEYS.format("open"))
        self.term.keys("Enter")
        shown = lines(self.on("", "add"))             # on a provider, the first row
        rows = [line[2:] for line in shown[2:shown.index(KEYS.format("add"))] if line[2:]]
        self.term.keys(*["Down"] * rows.index("OpenCode"), "Enter")
        self.on("  MiMo V2.6 Pro", "open")

    def on(self, row, enter):
        """The screen once the highlight is on the line that starts `row` and the key line
        names Enter as `enter`."""
        return self.term.wait(lambda screen: any(line.startswith(f"› {row}")
                                                 for line in lines(screen))
                              and key_line(screen) == KEYS.format(enter))

    def test_esc_goes_back_to_the_first_list_then_subscriptions(self):
        self.term.keys("Escape")
        self.assertEqual(title(self.on("OpenCode", "open")), ADD)
        self.term.keys("Escape")
        self.term.wait(lambda screen: title(screen) == PAGE)

    def test_a_model_added_lands_on_subscriptions(self):
        self.term.keys("Enter")
        self.on("  none", "add")
        self.term.keys("Enter")
        self.term.wait(lambda screen: title(screen) == PAGE)

    def test_ctrl_d_still_ends_on_subscriptions(self):
        self.term.keys("C-d")
        self.term.wait(lambda screen: title(screen) == PAGE)
        self.opencode()
        self.term.keys("Enter")
        self.on("  none", "add")
        self.term.keys("C-d")
        self.term.wait(lambda screen: title(screen) == PAGE)


if __name__ == "__main__":
    unittest.main()
