"""Another subscription of a provider is added by `+ add a subscription` on `c`'s `Subscriptions`,
removed under its row there: `+ add` lists one more of every provider the config has as the name
it will get (`Claude II`),
logs it in on the terminal under a fresh AGENTKIT_ACCOUNT and appends that name to the
provider's `accounts`, `default` first when it listed none; a login that fails adds nothing.
`− remove` under the row of each but the usual login of a provider with several asks with
`Keep` picked, takes that one name out of `accounts` and signs out that login alone.

Each test runs `menu.show_config` with a real `terminal.Keyboard` in a child process on a pty of
its own, through tests/test_config_matrix.py's Screen, in a temporary HOME.  The adapters are
fakes in that HOME that log each verb with the account it was asked for; nothing is logged in,
nothing here reads or writes the owner's ~/.agentkit or a harness's home, and the only process
signalled is the test's own child.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_config_matrix import DOWN, ENTER, Screen
from test_provider_screen import (ADD, KEYS, PAGE, back, choices, open_providers, open_row, pick,
                                  remove_asked, removing, subscriptions, title)
from agentkit import config, menu

FAKE = r"""#!/usr/bin/env bash
echo "%s $1 ${AGENTKIT_ACCOUNT-unset}" >> "$HOME/verbs.log"
if [ "$1" = login ]; then
  [ -e "$HOME/refuse" ] && { echo "<refused>"; exit 1; }
  [ -t 0 ] && [ -t 1 ] && echo "<%s login on the terminal>"
fi
exit 0
"""
CHILD = r"""
import os, sys
sys.path.insert(0, os.environ["MATRIX_REPO"])
from contextlib import closing
from pathlib import Path
from agentkit import config, menu, terminal, update

home = Path(os.environ["HOME"])
(home / "adapters").mkdir()
for harness in ("claude", "codex"):
    fake = home / "adapters" / f"{harness}.sh"
    fake.write_text(%r %% (harness, harness))
    fake.chmod(0o755)
os.environ["AGENTKIT_ADAPTER_DIR"] = str(home / "adapters")
config.catalog = lambda harness, cfg=None: []
update.version = lambda harness: ""
update.agentkit_version = lambda: "abc1234"
update.agentkit_newer = lambda: ""
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard)
print("<left>", flush=True)
""" % FAKE
CLAUDE = """
[defaults]
orchestrator = "opus"
workers = ["opus"]

[models.opus]
harness = "claude"
model = "claude-opus-5-5"
effort = "xhigh"
provider = "anthropic"

[providers.anthropic]
mode = "subscription"
"""
CODEX = """
[models.astra]
harness = "codex"
model = "gpt-7"
effort = "xhigh"
provider = "openai"

[providers.openai]
mode = "subscription"
"""
# What `+ add` lists for either config here: the shipped providers it has not, then one more
# subscription of each it has.
EVERY = 6


def rows(home):
    """The names on the menu's usage grid for the config in `home`, read by the menu's own
    loader, so a name `+ add` wrote is one the config accepts."""
    with tempfile.TemporaryDirectory(prefix="subscription-state-") as state, \
            mock.patch.object(config, "HOME", home / ".agentkit"), \
            mock.patch.object(config, "STATE", Path(state)):
        return [label for _, label, _, _ in menu.usage_cells(config.load())]


class AddSubscription(unittest.TestCase):
    def test_another_subscription_logs_in_under_a_fresh_name_and_joins_accounts(self):
        screen = Screen(self, child=CHILD, text=CLAUDE)
        home = screen.path.parent.parent
        open_providers(screen)
        _, offered = pick(screen, ENTER, ADD, EVERY)
        self.assertEqual(offered[-1], "  Claude II")       # after the providers not added
        mark = len(screen.text())
        screen.press(DOWN * (EVERY - 1) + ENTER, lambda lines: title(lines) == PAGE)
        # its login, then whose login it is, asked for the line its row opens
        [(harness, verb, account), asked] = [line.split() for line in
                                             (home / "verbs.log").read_text().splitlines()]
        self.assertEqual((harness, verb, asked), ("claude", "login", ["claude", "login-end",
                                                                      account]))
        said = screen.text()[mark:]
        self.assertLess(said.index("\x1b[?1049l"), said.index("<claude login on the terminal>"))
        self.assertEqual(screen.saved()["providers"]["anthropic"],
                         {"mode": "subscription", "accounts": ["default", account]})
        self.assertEqual(rows(home), ["Claude I", "Claude II"])     # the name it was offered as
        # a list that has names gets one more, fresh, at its end, under the next number
        open_providers(screen)
        _, offered = pick(screen, ENTER, ADD, EVERY)
        self.assertEqual(offered[-1], "  Claude III")
        screen.press(DOWN * (EVERY - 1) + ENTER, lambda lines: title(lines) == PAGE)
        third = (home / "verbs.log").read_text().splitlines()[-1].split()[-1]
        self.assertNotIn(third, ("default", account))
        self.assertEqual(screen.saved()["providers"]["anthropic"]["accounts"],
                         ["default", account, third])
        self.assertEqual(rows(home), ["Claude I", "Claude II", "Claude III"])
        back(screen)
        screen.leave()

    def test_a_login_that_fails_adds_nothing(self):
        screen = Screen(self, child=CHILD, text=CLAUDE + CODEX)
        home = screen.path.parent.parent
        (home / "refuse").touch()
        open_providers(screen)
        before = screen.path.read_bytes()
        _, offered = pick(screen, ENTER, ADD, EVERY)
        self.assertEqual(offered[-2:], ["  Claude II", "  ChatGPT II"])
        mark = len(screen.text())
        os.write(screen.master, DOWN * (EVERY - 1) + ENTER)    # no screen until it is read
        screen.saw("<refused>", after=mark)
        lines = screen.press(ENTER, lambda lines: title(lines) == PAGE)   # read, then back
        self.assertIn("codex login did not finish; ChatGPT II is not added", lines[-3])
        self.assertEqual(screen.path.read_bytes(), before)
        self.assertEqual(len((home / "verbs.log").read_text().split()), 3)
        back(screen)
        screen.leave()


class RemoveSubscription(unittest.TestCase):
    def test_one_subscription_goes_and_signs_out_its_login_alone(self):
        several = CLAUDE.replace('mode = "subscription"',
                                 'mode = "subscription"\naccounts = ["default", "a1", "b2"]')
        screen = Screen(self, child=CHILD, text=several + CODEX)
        home = screen.path.parent.parent
        before = screen.path.read_bytes()
        asked = remove_asked(screen, "Claude III")
        self.assertIn("  Remove Claude III?", asked)
        self.assertIn("  " + menu.REMOVE_SUBSCRIPTION_ASK[1], asked)
        mark = screen.text().rindex("Remove Claude III?")
        self.assertEqual(choices(screen, mark, 2), ["› ✓ Keep", "  ✗ Remove"])
        screen.press(ENTER, lambda lines: title(lines) == PAGE)            # Enter keeps
        self.assertEqual(screen.path.read_bytes(), before)
        removing(screen, lambda lines: lines[-1] == KEYS["ask"])
        screen.press(DOWN + ENTER, lambda lines: title(lines) == PAGE)
        saved = screen.saved()
        self.assertEqual(saved["providers"]["anthropic"]["accounts"], ["default", "a1"])
        self.assertEqual(set(saved["providers"]), {"anthropic", "openai"})
        self.assertEqual(set(saved["models"]), {"opus", "astra"})
        self.assertEqual([line for line in (home / "verbs.log").read_text().splitlines()
                          if " logout " in line], ["claude logout b2"])
        self.assertEqual(rows(home), ["Claude I", "Claude II", "ChatGPT"])
        back(screen)
        screen.leave()

    def test_the_last_provider_offers_only_its_subscriptions(self):
        several = CLAUDE.replace('mode = "subscription"',
                                 'mode = "subscription"\naccounts = ["default", "a1"]')
        screen = Screen(self, child=CHILD, text=several)
        open_row(screen, "Claude II")
        removing(screen, lambda lines: "  Remove Claude II?" in lines)
        lines = screen.press(DOWN + ENTER, lambda lines: title(lines) == PAGE)
        self.assertEqual(screen.saved()["providers"]["anthropic"]["accounts"], ["default"])
        # the usual login's row, the one left, is the last provider's: it stays
        before = screen.path.read_bytes()
        [left] = subscriptions(lines)
        open_row(screen, left)
        removing(screen, lambda lines: "the config needs one provider" in lines[-3])
        self.assertEqual(screen.path.read_bytes(), before)
        back(screen)
        screen.leave()


if __name__ == "__main__":
    unittest.main()
