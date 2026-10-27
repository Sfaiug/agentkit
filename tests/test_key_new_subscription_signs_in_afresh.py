"""Every subscription `+ add a subscription` on `c` adds is signed in afresh, under an account
name of its own, never on a login that was on disk before.

On 26 Oct the owner added Gemini, and ak ran its harness's `login` on the usual login, which
already held an old, forgotten account: the adapter answered that it was logged in, and Gemini
was added on that account with no sign-in at all.  The owner's word: an old login is never
reused when a subscription is added.  So a provider the config lacks is logged in under a new,
non-empty AGENTKIT_ACCOUNT and saved with exactly that account in its `accounts`; another
subscription of a provider the config has is too; a `login` that fails adds nothing; and the
list offers no login left on disk (`Use …`), not even one a `− remove` just took out.

Black-box: the program `AK_BIN` names, its menu in a person's terminal
(tests/fixtures/akterm.py), its harnesses the fakes of tests/fixtures/fakeadapter.py, which
answer every verb as a harness whose usual login is signed in, so a `login` on that login
returns at once, as the real adapters' do, and log each call with its AGENTKIT_ACCOUNT.  Judged
by what the terminal shows, config.toml and those calls; this test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
LIST_KEYS = "  ↑↓←→ move   ⏎ add   esc back"     # on its first row, a provider
PAGE, ADD = "agentkit · config · subscriptions", "agentkit · config · add a subscription"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def title(screen):
    """The screen's name on its header line, the clock off it."""
    return lines(screen)[0].rsplit(" ", 1)[0].strip()


def row_at(screen, row, mark="[› ]"):
    """The line of `row` on the screen, a subscription's with its meter after it, or None."""
    return next((number for number, line in enumerate(lines(screen))
                 if re.fullmatch(rf"{mark} {re.escape(row)}(  .*)?", line)), None)


def offered(screen):
    """The rows the list offers, the highlight's mark off them."""
    shown = lines(screen)
    return [line[2:] for line in shown[2:shown.index(LIST_KEYS)] if line[2:]]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NewSubscriptionSignsInAfresh(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")

    def open(self, models, providers=None):
        """The menu on `c`'s `Subscriptions` for a config of those models."""
        self.config = akconfig.write(self.home, models, providers=providers)
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen))
        self.term.keys("c")
        self.term.wait("› Fable 5.1")
        self.to("Subscriptions")
        self.term.keys("Enter")
        self.term.wait(lambda screen: title(screen) == PAGE)

    def to(self, row):
        """The highlight moved, a line at a time, onto the line that reads `row`."""
        for _ in range(20):
            screen = self.term.screen()
            if row_at(screen, row, "›") is not None:
                return
            shown = lines(screen)
            now = next(n for n, line in enumerate(shown) if line.startswith("› "))
            self.term.keys("Down" if row_at(screen, row) > now else "Up")
            self.term.wait(lambda screen: lines(screen)[now] != shown[now])
        self.fail(f"the highlight never reached {row}")

    def add_list(self):
        """`+ add a subscription`, and the rows it offers."""
        self.to("+ add a subscription")
        self.term.keys("Enter")
        # its frame is drawn before its rows
        return offered(self.term.wait(lambda screen: title(screen) == ADD
                                      and LIST_KEYS in lines(screen) and offered(screen)
                                      and "+ add a subscription" not in offered(screen)))

    def pick(self, row):
        rows = self.add_list()
        self.assertNotIn("", rows)
        self.term.keys(*["Down"] * rows.index(row), "Enter")

    def logins(self, harness):
        """The AGENTKIT_ACCOUNT each `login` of that harness ran under."""
        return [call["env"].get("AGENTKIT_ACCOUNT") for call in self.fakes[harness].calls("login")]

    def test_a_provider_the_config_lacks_signs_in_under_a_new_account_and_lists_only_it(self):
        self.open({"fable": "claude"})
        self.pick("OpenAI / Codex")
        self.term.wait(lambda screen: title(screen) == PAGE and "ChatGPT" in screen)
        [account] = self.logins("codex")
        self.assertTrue(account)                         # never the usual login
        saved = akconfig.read(self.home)["providers"]
        self.assertEqual(saved["openai"]["accounts"], [account])
        self.assertNotIn("accounts", saved["anthropic"])
        self.assertIsNotNone(row_at(self.term.screen(), "ChatGPT", "›"))   # its name, no numeral

    def test_a_login_that_fails_adds_no_provider_and_no_account(self):
        self.open({"fable": "claude"})
        before = self.config.read_text()
        self.fakes["codex"].answer("login", "<refused>", 1)
        self.pick("OpenAI / Codex")
        self.term.wait("<refused>")
        self.term.keys("Enter")                           # what it said read
        self.term.wait(lambda screen: title(screen) == PAGE
                       and "codex login did not finish; OpenAI / Codex is not added" in screen)
        [account] = self.logins("codex")
        self.assertTrue(account)
        self.assertEqual(self.config.read_text(), before)

    def test_each_sign_in_opens_on_a_screen_of_its_own(self):
        self.open({"fable": "claude"})
        self.fakes["codex"].answer("login", "<codex says>", 1)
        self.pick("OpenAI / Codex")
        self.term.wait("<codex says>")
        self.term.keys("Enter")
        self.term.wait(lambda screen: title(screen) == PAGE and "is not added" in screen)
        self.fakes["claude"].answer("login", "<claude says>", 1)
        self.pick("Claude II")
        self.assertNotIn("<codex says>", self.term.wait("<claude says>"))

    def test_a_second_subscription_signs_in_under_a_new_account(self):
        self.open({"fable": "claude"})
        self.pick("Claude II")
        self.term.wait(lambda screen: title(screen) == PAGE and "Claude II" in screen)
        [account] = self.logins("claude")
        self.assertNotIn(account, ("", "default", None))
        self.assertEqual(akconfig.read(self.home)["providers"]["anthropic"]["accounts"],
                         ["default", account])

    def test_no_login_on_disk_is_offered_even_one_just_removed(self):
        self.open({"fable": "claude", "astra": "codex"},
                  providers={"anthropic": {"mode": "subscription", "accounts": ["default", "a1"]}})
        self.assertFalse([row for row in self.add_list() if row.startswith("Use ")])
        self.term.keys("Escape")
        self.term.wait(lambda screen: title(screen) == PAGE)
        # `− remove` under Claude II, then ChatGPT whole
        for row in ("Claude II", "ChatGPT"):
            self.to(row)
            self.term.keys("Right", "Right", "Enter")      # `− remove`, last on its line
            self.term.wait(lambda screen: "  ✗ Remove" in lines(screen))
            self.term.keys("Down", "Enter")
            self.term.wait(lambda screen: title(screen) == PAGE and row_at(screen, row) is None)
        saved = akconfig.read(self.home)["providers"]
        self.assertEqual((saved["anthropic"]["accounts"], "openai" in saved), (["default"], False))
        rows = self.add_list()
        self.assertIn("OpenAI / Codex", rows)
        self.assertFalse([row for row in rows if row.startswith("Use ")], rows)


if __name__ == "__main__":
    unittest.main()
