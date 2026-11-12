"""A model listing a harness answered stands, on every screen and in every process, until a
newer one is read: a listing that fails replaces nothing, and the harness's `[catalog]` table
stands in only for a login no listing was ever read of.

On 12 Nov 2026 a harness's own listing answered in 8 to 36 seconds on a loaded host, and its
table, without the model the owner's upgraded subscription had just opened, stood in for every
answer past ten seconds.  Black-box: `AK_BIN`'s menu in a person's terminal
(tests/fixtures/akterm.py), its harnesses the fakes of tests/fixtures/fakeadapter.py, the fake
OpenCode logged in to MiMo and Acme and listing `acme/acme-9`, then failing.  Judged by what
`+ add a subscription` offers under OpenCode; this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_lists_name_what_enter_does import KEYS, downs_to_opencode
from test_key_lists_space_marks_enter_picks import MAIN_KEYS, lines

# before the fake itself: the providers OpenCode is logged in to
PROVIDERS = """[ "$1" = providers ] && { printf 'mimo\\tMiMo\\tpayg\\nacme\\tAcme\\tsubscription\\n'; exit 0; }
"""
LOGGED_IN = ("MiMo", "Acme")
ACME_9 = "acme/acme-9\tAcme 9\thigh"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LiveListingStands(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakes = fakeadapter.install(self.home, claude="pass", codex="pass", opencode="pass")
        self.opencode = fakes["opencode"]
        self.opencode.script.write_text(self.opencode.script.read_text().replace(
            "#!/bin/sh\n", "#!/bin/sh\n" + PROVIDERS, 1))
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"})

    def offered(self):
        """A menu of its own, in a process of its own, on `+ add a subscription`'s OpenCode list:
        the model it offers first, highlighted, once that list is drawn."""
        term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait(lambda screen: MAIN_KEYS in lines(screen))
        term.keys("c")
        term.wait("› Fable 5.1")
        term.keys("Down", "Down", "Down")             # past GPT-6-Astra and `Models`
        term.wait("› Subscriptions")
        term.keys("Enter")
        term.wait("+ add a subscription")
        term.keys("Down", "Down")                     # past ChatGPT
        term.wait(KEYS.format("open"))
        term.keys("Enter")
        term.keys(*["Down"] * downs_to_opencode(term), "Enter")
        # its frame is drawn before its rows: read once the highlighted row is a model, beside
        # the provider it runs through, never the row the list before left there
        model = lambda screen: next((line[2:].strip().split("  ")[0] for line in lines(screen)
                                     if line.startswith("› ") and line.split()[-1] in LOGGED_IN),
                                    None)
        shown = term.wait(lambda screen: "· add a subscription · OpenCode" in screen
                          and model(screen))
        self.home.tmux("respawn-pane", "-k", "-t", term.pane, "sleep 86400", server=SERVER)
        return model(shown)

    def test_a_listing_read_stands_after_a_failure_and_in_a_new_process(self):
        self.opencode.answer("models", ACME_9)
        self.assertEqual(self.offered(), "Acme 9")
        self.opencode.answer("models", "", 1)
        asked = len(self.opencode.calls("models"))
        self.assertEqual(self.offered(), "Acme 9")
        self.assertGreater(len(self.opencode.calls("models")), asked, "asked again, and failed")

    def test_a_harness_never_listed_offers_its_table(self):
        self.opencode.answer("models", "", 1)
        self.assertEqual(self.offered(), "MiMo V2.6 Pro")
        self.assertTrue(self.opencode.calls("models"))


if __name__ == "__main__":
    unittest.main()
