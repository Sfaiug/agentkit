"""Another subscription of a provider is added and removed on the `c` screen's Providers row:
`+ add` lists one more of every provider the config has as the name it will get (`Claude II`),
logs it in on the terminal under a fresh AGENTKIT_ACCOUNT and appends that name to the
provider's `accounts`, `default` first when it listed none; a login that fails adds nothing.
`− remove` lists each subscription of a provider with several but the usual login, asks with
`Keep` picked, and takes that one name out of `accounts`, leaving its login files on disk.

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

from test_config_matrix import DOWN, ENTER, RIGHT, Screen
from test_provider_screen import ADD, KEYS, MATRIX, REMOVE, choices, open_providers, pick, title
from agentkit import config, menu, terminal

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
config.catalog = lambda harness: []
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
    """The names on the menu's usage rows for the config in `home`, read by the menu's own
    loader, so a name `+ add` wrote is one the config accepts."""
    with tempfile.TemporaryDirectory(prefix="subscription-state-") as state, \
            mock.patch.object(config, "HOME", home / ".agentkit"), \
            mock.patch.object(config, "STATE", Path(state)):
        return [terminal.ANSI.sub("", line)[2:].split("  ")[0]
                for line in menu.usage_lines(config.load(), 100)[1:]]


class AddSubscription(unittest.TestCase):
    def test_another_subscription_logs_in_under_a_fresh_name_and_joins_accounts(self):
        screen = Screen(self, child=CHILD, text=CLAUDE)
        home = screen.path.parent.parent
        open_providers(screen)
        _, offered = pick(screen, ENTER, ADD, EVERY)
        self.assertEqual(offered[-1], "  Claude II")       # after the providers not added
        mark = len(screen.text())
        screen.press(DOWN * (EVERY - 1) + ENTER, lambda lines: title(lines) == MATRIX)
        [(harness, verb, account)] = [line.split() for line in
                                      (home / "verbs.log").read_text().splitlines()]
        self.assertEqual((harness, verb), ("claude", "login"))
        said = screen.text()[mark:]
        self.assertLess(said.index("\x1b[?1049l"), said.index("<claude login on the terminal>"))
        self.assertEqual(screen.saved()["providers"]["anthropic"],
                         {"mode": "subscription", "accounts": ["default", account]})
        self.assertEqual(rows(home), ["Claude I", "Claude II"])     # the name it was offered as
        # a list that has names gets one more, fresh, at its end, under the next number
        _, offered = pick(screen, ENTER, ADD, EVERY)
        self.assertEqual(offered[-1], "  Claude III")
        screen.press(DOWN * (EVERY - 1) + ENTER, lambda lines: title(lines) == MATRIX)
        third = (home / "verbs.log").read_text().splitlines()[-1].split()[-1]
        self.assertNotIn(third, ("default", account))
        self.assertEqual(screen.saved()["providers"]["anthropic"]["accounts"],
                         ["default", account, third])
        self.assertEqual(rows(home), ["Claude I", "Claude II", "Claude III"])
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
        lines = screen.press(ENTER, lambda lines: title(lines) == MATRIX)   # read, then back
        self.assertIn("codex login did not finish; ChatGPT II is not added", lines[-3])
        self.assertEqual(screen.path.read_bytes(), before)
        self.assertEqual(len((home / "verbs.log").read_text().split()), 3)
        screen.leave()


class RemoveSubscription(unittest.TestCase):
    def test_one_subscription_goes_and_its_login_stays(self):
        several = CLAUDE.replace('mode = "subscription"',
                                 'mode = "subscription"\naccounts = ["default", "a1", "b2"]')
        screen = Screen(self, child=CHILD, text=several + CODEX)
        home = screen.path.parent.parent
        (home / ".claude-b2").mkdir()
        (home / ".claude-b2" / ".credentials.json").write_text("{}")
        open_providers(screen)
        before = screen.path.read_bytes()
        _, listed = pick(screen, RIGHT + ENTER, REMOVE, 4)
        # by the name its usage row has, the usual login never
        self.assertEqual(listed, ["› Claude", "  Claude II", "  Claude III", "  ChatGPT"])
        asked = screen.press(DOWN * 2 + ENTER, lambda lines: lines[-1] == KEYS["ask"])
        self.assertIn("  Remove Claude III?", asked)
        self.assertIn("  Nothing new starts on it; its login stays on this machine.", asked)
        mark = screen.text().rindex("Remove Claude III?")
        self.assertEqual(choices(screen, mark, 2), ["› ✓ Keep", "  ✗ Remove"])
        screen.press(ENTER, lambda lines: title(lines) == MATRIX)          # Enter keeps
        self.assertEqual(screen.path.read_bytes(), before)
        pick(screen, ENTER, REMOVE, 4)
        screen.press(DOWN * 2 + ENTER, lambda lines: lines[-1] == KEYS["ask"])
        screen.press(DOWN + ENTER, lambda lines: title(lines) == MATRIX)
        saved = screen.saved()
        self.assertEqual(saved["providers"]["anthropic"]["accounts"], ["default", "a1"])
        self.assertEqual(set(saved["providers"]), {"anthropic", "openai"})
        self.assertEqual(set(saved["models"]), {"opus", "astra"})
        self.assertTrue((home / ".claude-b2" / ".credentials.json").exists())
        self.assertEqual(rows(home), ["Claude I", "Claude II", "ChatGPT"])
        screen.leave()

    def test_the_last_provider_offers_only_its_subscriptions(self):
        several = CLAUDE.replace('mode = "subscription"',
                                 'mode = "subscription"\naccounts = ["default", "a1"]')
        screen = Screen(self, child=CHILD, text=several)
        open_providers(screen)
        _, listed = pick(screen, RIGHT + ENTER, REMOVE, 1)
        self.assertEqual(listed, ["› Claude II"])
        screen.press(ENTER, lambda lines: "  Remove Claude II?" in lines)
        screen.press(DOWN + ENTER, lambda lines: title(lines) == MATRIX)
        self.assertEqual(screen.saved()["providers"]["anthropic"]["accounts"], ["default"])
        # the usual login alone is one subscription: nothing is left to offer
        before = screen.path.read_bytes()
        screen.press(ENTER, lambda lines: "the config needs one provider" in lines[-3])
        self.assertEqual(screen.path.read_bytes(), before)
        screen.leave()


if __name__ == "__main__":
    unittest.main()
