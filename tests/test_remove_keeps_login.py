"""A login `− remove` took out of ak stays on disk and is offered again on `+ add`: `Use <who>`,
<who> being who the adapter's `auth` says it is logged in as, else the name its usage row had.
Picking it puts it back with no login -- a subscription into `accounts` under its old name, a
provider as it ships -- and its usage row returns.  One whose `auth` fails is not offered.

Each test runs `menu.show_config` with a real `terminal.Keyboard` in a child process on a pty of
its own, through tests/test_config_matrix.py's Screen, in a temporary HOME.  The adapters are
fakes in that HOME that log each verb with the account it was asked for, and whose `auth` passes
on a `login` file in a home of that account's own; nothing is logged in, nothing here reads or
writes the owner's ~/.agentkit or a harness's home, and the only process signalled is the test's
own child.
"""

import unittest

from test_add_subscription import CLAUDE, CODEX, rows
from test_config_matrix import DOWN, ENTER, ESC, LEFT, RIGHT, Screen
from test_provider_screen import (ADD, GIVE, KEYS, MATRIX, REMOVE, SHIPPED, open_providers,
                                  pick, title)

FAKE = r"""#!/usr/bin/env bash
H=%s ACCOUNT=${AGENTKIT_ACCOUNT:-default}
echo "$H $1 $ACCOUNT" >> "$HOME/verbs.log"
LOGIN="$HOME/.$H-$ACCOUNT/login"
case $1 in
  auth) [ -e "$LOGIN" ] || { echo "$H: no $LOGIN" >&2; exit 1; }
        who=$(cat "$LOGIN"); echo "$H: the login in $LOGIN is saved${who:+; logged in as $who}" ;;
esac
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
    fake.write_text(%r %% harness)
    fake.chmod(0o755)
os.environ["AGENTKIT_ADAPTER_DIR"] = str(home / "adapters")
config.harness_binary = lambda name: name        # every program is here: nothing installed
config.catalog = lambda harness: [{"id": "gpt-7", "label": "GPT-7", "efforts": ["low", "xhigh"]}]
update.version = lambda harness: ""
update.agentkit_version = lambda: "abc1234"
update.agentkit_newer = lambda: ""
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard)
print("<left>", flush=True)
""" % FAKE
SEVERAL = CLAUDE.replace('mode = "subscription"',
                         'mode = "subscription"\naccounts = ["default", "a1", "b2"]') + CODEX


def logged_in(home, harness, account, who=""):
    """A login of that account in a home of its own, the file the fake `auth` passes on."""
    path = home / f".{harness}-{account}" / "login"
    path.parent.mkdir()
    path.write_text(who)
    return path


def verbs(home, verb):
    """Each `harness account` the fakes were asked `verb` for."""
    lines = (home / "verbs.log").read_text().splitlines() if (home / "verbs.log").exists() else []
    return [f"{harness} {account}" for harness, asked, account in map(str.split, lines)
            if asked == verb]


def remove(screen, down, count):
    """`− remove` on the Providers row, the one `down` rows into its `count`, and `Remove`."""
    pick(screen, RIGHT + ENTER, REMOVE, count)
    screen.press(DOWN * down + ENTER, lambda lines: lines[-1] == KEYS["ask"])
    screen.press(DOWN + ENTER, lambda lines: title(lines) == MATRIX)
    screen.press(LEFT, lambda lines: title(lines) == MATRIX)          # back onto `+ add`


class RemoveKeepsLogin(unittest.TestCase):
    def test_a_removed_subscription_is_offered_by_who_it_is_and_comes_back_without_a_login(self):
        screen = Screen(self, child=CHILD, text=SEVERAL)
        home = screen.path.parent.parent
        login = logged_in(home, "claude", "b2", "bo@acme.test")
        open_providers(screen)
        remove(screen, 2, 4)                                         # Claude III
        self.assertEqual(screen.saved()["providers"]["anthropic"]["accounts"], ["default", "a1"])
        self.assertTrue(login.exists())
        self.assertEqual(rows(home), ["Claude I", "Claude II", "ChatGPT"])
        _, offered = pick(screen, ENTER, ADD, 7)
        self.assertEqual(offered[-3:], ["  Claude III", "  ChatGPT II", "  Use bo@acme.test"])
        mark = len(screen.text())
        screen.press(DOWN * 6 + ENTER, lambda lines: title(lines) == MATRIX)
        self.assertEqual(verbs(home, "login"), [])
        self.assertNotIn(GIVE, screen.text()[mark:])                 # the terminal never left
        self.assertEqual(screen.saved()["providers"]["anthropic"]["accounts"],
                         ["default", "a1", "b2"])
        self.assertEqual(rows(home), ["Claude I", "Claude II", "Claude III", "ChatGPT"])
        # back in ak, it is offered no more
        mark = len(screen.text())
        pick(screen, ENTER, ADD, 6)
        screen.press(ESC, lambda lines: title(lines) == MATRIX)
        self.assertNotIn("Use ", screen.text()[mark:])
        screen.leave()

    def test_a_removed_provider_s_login_is_offered_by_its_row_s_name_and_comes_back_as_it_ships(
            self):
        screen = Screen(self, child=CHILD, text=CLAUDE + CODEX)
        home = screen.path.parent.parent
        login = logged_in(home, "codex", "default")                 # it says nobody
        open_providers(screen)
        remove(screen, 1, 2)                                         # ChatGPT, whole
        self.assertNotIn("openai", screen.saved()["providers"])
        self.assertTrue(login.exists())
        _, offered = pick(screen, ENTER, ADD, 7)
        self.assertEqual(offered[0], "› OpenAI / Codex")
        self.assertEqual(offered[-2:], ["  Claude II", "  Use ChatGPT"])
        screen.press(DOWN * 6 + ENTER, lambda lines: title(lines) == MATRIX and "ChatGPT" in lines)
        self.assertEqual(verbs(home, "login"), [])
        saved = screen.saved()
        self.assertEqual(saved["providers"]["openai"], SHIPPED["providers"]["openai"])
        self.assertEqual(saved["models"]["astra"], {"harness": "codex", "model": "gpt-7",
                                                    "effort": "xhigh", "provider": "openai"})
        self.assertEqual(rows(home), ["Claude", "ChatGPT"])
        screen.leave()

    def test_a_kept_login_whose_auth_fails_is_not_offered(self):
        screen = Screen(self, child=CHILD, text=SEVERAL)
        home = screen.path.parent.parent
        kept = [home / ".claude-b2" / ".credentials.json", home / ".codex" / "auth.json"]
        for path in kept:                        # its files, but no login the fake `auth` takes
            path.parent.mkdir()
            path.write_text("{}")
        open_providers(screen)
        remove(screen, 2, 4)                                         # Claude III
        remove(screen, 2, 3)                                         # ChatGPT, whole
        self.assertEqual(list(screen.saved()["providers"]), ["anthropic"])
        mark = len(screen.text())
        _, offered = pick(screen, ENTER, ADD, 6)
        self.assertEqual(offered[-1], "  Claude III")               # the fresh one, a new login
        screen.press(ESC, lambda lines: title(lines) == MATRIX)
        self.assertNotIn("Use ", screen.text()[mark:])
        self.assertEqual(verbs(home, "auth")[-2:], ["claude b2", "codex default"])    # asked
        for path in kept:
            self.assertTrue(path.exists(), path)
        screen.leave()


if __name__ == "__main__":
    unittest.main()
