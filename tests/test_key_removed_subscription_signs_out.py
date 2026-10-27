"""`− remove` on a subscription signs its login out on this machine, and no other login.

On 26 Oct the owner's word: a login that is removed should not stay saved.  So once the config
is saved without it, the removed subscription's harness runs its adapter's `logout` for that
account alone; a provider removed whole signs out each of its subscriptions; and a `logout` that
fails leaves the subscription removed and says, under the page, which login stayed.

Black-box: the program `AK_BIN` names, its menu in a person's terminal (tests/fixtures/akterm.py),
its harnesses the fakes of tests/fixtures/fakeadapter.py, but for Claude's `logout`, which is
the real adapters/claude.sh over a stub `claude` that signs out the login of the config
directory it is run in.  Judged by what the terminal shows, config.toml and the login files
under a temporary HOME; this test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, REPO, Home
from fixtures.akterm import SERVER, Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ choose   n new   c config   esc leave"
PAGE = "agentkit · config · subscriptions"
# Claude Code's own sign-out, as `claude auth logout` does it: its config directory's login gone
CLAUDE = """#!/bin/sh
[ "$*" = "auth logout" ] || exit 2
[ ! -e "$HOME/logout-refused" ] || exit 1
rm -f "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.credentials.json"
"""
ACCOUNTS = {"anthropic": {"mode": "subscription", "accounts": ["default", "a1", "b2"]}}


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def title(screen):
    """The screen's name on its header line, the clock off it."""
    return lines(screen)[0].rsplit(" ", 1)[0].strip()


def row_at(screen, row, mark="[› ]"):
    """The line of `row` on the screen, a subscription's with its meter after it, or None."""
    return next((number for number, line in enumerate(lines(screen))
                 if re.fullmatch(rf"{mark} {re.escape(row)}(  .*)?", line)), None)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RemovedSubscriptionSignsOut(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        script = self.fakes["claude"].script
        shebang, rest = script.read_text().split("\n", 1)
        script.write_text(f'{shebang}\n[ "$1" != logout ] || exec bash '
                          f'{REPO / "adapters/claude.sh"} "$@"\n{rest}')
        self.home.fake("claude", CLAUDE)
        self.home.fake("security", "#!/bin/sh\nexit 1\n")      # no Keychain: the login is the file
        self.logins = {account: (
            self.home.write(f".claude{account and '-' + account}/.credentials.json",
                            {"claudeAiOauth": {"accessToken": f"seat-{account}"}}),
            self.home.write(f".agentkit/secrets/claude_oauth_token{account and '.' + account}",
                            "worker\n")) for account in ("", "a1", "b2")}
        self.codex = self.home.write(".codex/auth.json", {"tokens": {"access_token": "chatgpt"}})
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"}, providers=ACCOUNTS)
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

    def remove(self, row, asked):
        """`− remove` under `row`, the card's words checked, and Remove picked: the page after."""
        self.to(row)
        self.term.keys("Right", "Right", "Enter")          # `− remove`, last on its line
        self.assertIn(asked, lines(self.term.wait(lambda screen: "  ✗ Remove" in lines(screen))))
        self.term.keys("Down", "Enter")
        return self.term.wait(lambda screen: title(screen) == PAGE and row_at(screen, row) is None)

    def signed_in(self):
        """Which Claude logins are still on disk, seat and worker token alike."""
        return {account: [path.exists() for path in paths]
                for account, paths in self.logins.items()}

    def test_a_named_subscription_signs_out_its_login_alone(self):
        self.remove("Claude III",
                    "  Nothing new starts on it, and its login is signed out on this machine.")
        self.assertEqual(akconfig.read(self.home)["providers"]["anthropic"]["accounts"],
                         ["default", "a1"])
        self.assertEqual(self.signed_in(),
                         {"": [True, True], "a1": [True, True], "b2": [False, False]})
        self.assertTrue(self.codex.exists())

    def test_a_whole_provider_signs_out_each_of_its_subscriptions(self):
        self.remove("Claude I",
                    "  Its models leave the config, and its logins are signed out on this machine.")
        self.assertNotIn("anthropic", akconfig.read(self.home)["providers"])
        self.assertEqual(self.signed_in(),
                         {"": [False, False], "a1": [False, False], "b2": [False, False]})
        self.assertTrue(self.codex.exists())
        self.assertEqual(self.fakes["codex"].calls("logout"), [])

    def test_a_failed_sign_out_still_removes_and_says_which_login_stayed(self):
        self.home.write("logout-refused", "")
        screen = self.remove("Claude III", "  Nothing new starts on it, and its login is signed"
                                           " out on this machine.")
        self.assertIn("Claude III's login is still on this machine; sign it out with "
                      "AGENTKIT_ACCOUNT=b2", " ".join(lines(screen)))
        self.assertEqual(akconfig.read(self.home)["providers"]["anthropic"]["accounts"],
                         ["default", "a1"])
        self.assertEqual(self.signed_in()["b2"][0], True)


if __name__ == "__main__":
    unittest.main()
