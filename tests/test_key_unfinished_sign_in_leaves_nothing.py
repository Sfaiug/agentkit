"""A sign-in for a new account that does not finish leaves nothing of that account behind, and a
`↻ log in again` that does not finish says so.

`+ add a subscription` signs in under a new random account.  On 27 Oct a cancelled `Claude IV`
left `~/.claude-<account>` behind, and earlier attempts left `~/.gemini/antigravity-cli-<name>`
and `~/.grok-<name>` for accounts no subscription lists, one holding a signed-in token.  The
owner's word (26 Oct): a login that is not a subscription's does not stay saved.  So, for each
harness that keeps more than one login, an add whose sign-in quits leaves the HOME as it was
before the add, outside ak's own state; and a `↻ log in again` that does not finish says so
under the page, its login left where it was.

Black-box: the program `AK_BIN` names, its menu in a person's terminal
(tests/fixtures/akterm.py), each harness's real adapter over a stub of its program that writes
where that harness keeps an account's files and quits without signing in.  The HOME holds each
harness's usual home, as one it has run in does, so what an account links to is there before.
Judged by the files under HOME and what the terminal shows.
"""

import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_new_subscription_signs_in_afresh import ADD, MAIN_KEYS, PAGE, lines, row_at, title

KEYS = "  ↑↓←→ move   "      # the key line, whatever Enter does on the row lit
QUIT = "<quit without signing in>"
# Each harness's program, as its adapter calls it to sign in: a file where that harness keeps
# the account's own (the home its adapter names in a variable, or agy's --app_data_dir), then a
# quit.  Anything else it is asked fails.
STUB = """#!/bin/sh
case "$*" in
  *--app_data_dir=*) dir=$HOME/.gemini/${1#--app_data_dir=} ;;
  *login*) dir=${CLAUDE_CONFIG_DIR:-${CODEX_HOME:-${GROK_HOME:-$XDG_CONFIG_HOME/muse}}} ;;
  *) exit 1 ;;
esac
mkdir -p "$dir" && echo '{}' >"$dir/half-made.json"
echo "%s"
exit 1
""" % QUIT
PROGRAMS = ("claude", "codex", "agy", "grok", "muse")
# What each harness's usual login leaves, which an account's home links to.
USUAL = {".claude/settings.json": "{}", ".claude/projects/.keep": "",
         ".codex/sessions/.keep": "", ".codex/archived_sessions/.keep": "",
         ".codex/config.toml": "", ".gemini/antigravity-cli/conversations/.keep": "",
         ".gemini/antigravity-cli/brain/.keep": "", ".grok/sessions/.keep": "",
         ".grok/config.toml": "", ".config/muse/settings.json": '{"schema_version":1}\n',
         ".config/muse/.settings.json.lock": ""}


def offered(screen):
    """The rows a list offers, the highlight's mark off them."""
    shown = lines(screen)
    end = next((number for number, line in enumerate(shown) if line.startswith(KEYS)), 2)
    return [line[2:] for line in shown[2:end] if line[2:]]


def on_page(screen):
    """Whether the screen is Subscriptions with its rows: its frame is drawn before them."""
    return title(screen) == PAGE and row_at(screen, "+ add a subscription") is not None


def files(home):
    """Every path under HOME but ak's own state, with what it holds or where it links."""
    found = {}
    for top, dirs, names in os.walk(home.path):
        here = Path(top)
        if here == home.path:
            dirs.remove(".agentkit")
        for name in dirs + names:
            path = here / name
            found[str(path.relative_to(home.path))] = (
                f"-> {os.readlink(path)}" if path.is_symlink() else "dir" if path.is_dir()
                else path.read_bytes())
    return found


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class UnfinishedSignInLeavesNothing(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        for program in PROGRAMS:
            self.home.fake(program, STUB)
        for path, text in USUAL.items():
            self.home.write(path, text)

    def open(self, models, providers=None):
        """The menu on `c`'s `Subscriptions` for a config of those models."""
        akconfig.write(self.home, models, providers=providers)
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen))
        self.term.keys("c")
        self.term.wait("› Fable 5.1")
        self.to("Subscriptions")
        self.term.keys("Enter")
        self.term.wait(on_page)

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

    def quit_sign_in(self, row):
        """`row` picked under `+ add a subscription`, and its sign-in quit."""
        self.to("+ add a subscription")
        self.term.keys("Enter")
        # its frame is drawn before its rows, top to bottom
        rows = offered(self.term.wait(lambda screen: title(screen) == ADD
                                      and row in offered(screen)))
        self.term.keys(*["Down"] * rows.index(row), "Enter")
        self.term.wait(QUIT)

    def add_quitting(self, row):
        """`row`'s sign-in quit, and the page back saying so."""
        self.quit_sign_in(row)
        self.term.keys("Enter")                           # what it said read
        self.term.wait(lambda screen: on_page(screen) and "is not added" in screen)

    def test_an_add_whose_sign_in_quits_leaves_the_home_as_it_was(self):
        self.open({"fable": "claude", "astra": "codex", "gemini": "antigravity",
                   "grok": "grokbuild", "spark": "muse"})
        for row in ("Claude II", "ChatGPT II", "Gemini II", "Grok II", "Muse II"):
            with self.subTest(row=row):
                before = files(self.home)
                self.add_quitting(row)
                self.assertEqual(files(self.home), before)

    def test_a_provider_the_config_lacks_leaves_nothing_either(self):
        self.open({"fable": "claude"})
        before = files(self.home)
        self.add_quitting("OpenAI / Codex")
        self.assertEqual(files(self.home), before)

    def test_an_add_ended_while_what_its_sign_in_said_waits_leaves_nothing_either(self):
        self.open({"fable": "claude"})
        before = files(self.home)
        self.quit_sign_in("Claude II")
        self.term.wait("esc back")                        # the screen was cleared for the quit
        self.term.keys("C-c")
        self.term.exit_code()
        self.assertEqual(files(self.home), before)

    def test_a_log_in_again_that_does_not_finish_says_so_and_keeps_its_login(self):
        self.home.write(".claude-a1/.credentials.json", "{}")
        # a login ending tomorrow, so `↻ log in again` is offered
        self.home.write(".agentkit/state/logins.json", {"anthropic": {"a1": {
            "ends": time.time() + 86400, "checked_at": time.time()}}})
        self.open({"fable": "claude"},
                  providers={"anthropic": {"mode": "subscription", "accounts": ["default", "a1"]}})
        self.to("Claude II")
        self.term.wait(f"{KEYS}⏎ log in again")           # first on its line, lit as it opens
        self.term.keys("Enter")
        self.term.wait(QUIT)
        self.term.keys("Enter")                           # what it said read
        self.term.wait(lambda screen: on_page(screen)
                       and "Claude II's sign-in did not finish" in screen)
        self.assertEqual(files(self.home)[".claude-a1/.credentials.json"], b"{}")


if __name__ == "__main__":
    unittest.main()
