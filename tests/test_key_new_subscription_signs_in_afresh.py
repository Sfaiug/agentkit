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
    """The rows the list offers, the highlight's mark off them: every line under the rule down
    to the blank one over its keys, one not drawn yet blank."""
    shown = lines(screen)
    return [line[2:] for line in shown[2:shown.index(LIST_KEYS) - 1]]


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
            # a whole frame: one the terminal has only begun to read shows its first lines
            # over the last screen's, with the row missing or a highlight too many or too few
            screen = self.term.wait(lambda screen: row_at(screen, row) is not None and sum(
                line.startswith("› ") for line in lines(screen)) == 1)
            if row_at(screen, row, "›") is not None:
                return
            shown = lines(screen)
            now = next(n for n, line in enumerate(shown) if line.startswith("› "))
            self.term.keys("Down" if row_at(screen, row) > now else "Up")
            self.term.wait(lambda screen: lines(screen)[now] != shown[now])
        self.fail(f"the highlight never reached {row}")

    def add_list(self, row=None):
        """`+ add a subscription`, and the rows it offers, `row` among them when one is named."""
        self.to("+ add a subscription")
        self.term.keys("Enter")
        # every row drawn, and `row` whole: its frame comes first with them blank, then they go
        # in a line at a time, and the last one read can be half written
        return offered(self.term.wait(lambda screen: title(screen) == ADD
                                      and LIST_KEYS in lines(screen) and offered(screen)
                                      and "" not in offered(screen)
                                      and "+ add a subscription" not in offered(screen)
                                      and (row is None or row in offered(screen))))

    def pick(self, row):
        rows = self.add_list(row)
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

    def test_a_login_that_fails_adds_nothing_and_says_so_in_its_harness_s_name(self):
        self.open({"fable": "claude"})
        before = self.config.read_text()
        self.fakes["codex"].answer("login", "<refused>", 1)
        self.pick("OpenAI / Codex")
        self.term.wait("<refused>")
        self.term.keys("Enter")                           # what it said read
        self.term.wait(lambda screen: title(screen) == PAGE
                       and "Codex login did not finish; OpenAI / Codex is not added" in screen)
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

    def test_ctrl_c_ends_a_sign_in_and_not_the_menu(self):
        self.open({"fable": "claude"})
        self.fakes["codex"].answer("login", "<enter the code>", None)   # as codex's device code
        self.pick("OpenAI / Codex")
        self.term.wait("<enter the code>")
        self.term.keys("C-c")
        self.term.wait(lambda screen: "<enter the code>" in screen and "esc back" in screen)
        self.term.keys("Enter")
        self.term.wait(lambda screen: title(screen) == PAGE
                       and "Codex login did not finish; OpenAI / Codex is not added" in screen)

    def test_a_sign_in_that_exits_0_with_no_login_adds_nothing(self):
        self.open({"fable": "claude"})
        before = self.config.read_text()
        self.fakes["codex"].answer("login", "<cut short>", 0)        # as codex 0.163's on ^C
        self.fakes["codex"].answer("auth", "<no login>", 1)
        self.pick("OpenAI / Codex")
        self.term.wait(lambda screen: "<cut short>" in screen and "esc back" in screen)
        self.term.keys("Enter")
        self.term.wait(lambda screen: title(screen) == PAGE
                       and "Codex login did not finish; OpenAI / Codex is not added" in screen)
        self.assertEqual(self.config.read_text(), before)

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
