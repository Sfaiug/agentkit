"""`Subscriptions` in `c` adds a provider the way it ships and removes one: `+ add a
subscription` offers the shipped default's providers the config has not, installs the picked
one's harness when its program is missing, logs it in on the terminal, then adds its shipped table
and its first catalog model; `− remove` under a subscription's row asks with `Keep` picked and
takes its models, the last provider stays, and a free provider, which has no meter, goes with its
last model.

Each test runs `menu.show_config` with a real `terminal.Keyboard` in a child process on a pty of
its own, through tests/test_config_matrix.py's Screen, in a temporary HOME.  The adapters are
fakes in that HOME: each logs the verbs it is asked, `install` puts an empty program in a bin
dir of the HOME's own -- the only place the child looks for one -- and `login` says whether it
had the terminal.  The catalogs are faked too.  Nothing is installed or logged in, nothing here
reads or writes the owner's ~/.agentkit or a harness's home, and the only process signalled is
the test's own child.
"""

import copy
import io
import os
import re
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from test_config_matrix import (DOWN, ENTER, ESC, REPO, RIGHT, UP, Screen, headings,
                                highlighted)
from fixtures.sandbox import menu_input
from agentkit import config, menu, terminal

PROGRAMS = {"claude": "claude", "codex": "codex", "muse": "muse", "grokbuild": "grok",
            "opencode": "opencode", "antigravity": "agy"}
# Grok's first entry says no efforts, so it is added at Grok's own (config.efforts).
CATALOG = {"grokbuild": [("grok-mystery", "Mystery", []),
                         ("grok-5", "Grok 5", ["low", "medium", "high"])],
           "codex": [("gpt-7", "GPT-7", ["low", "high", "xhigh"])],
           "muse": [("muse-spark-2", "muse-spark-2", ["minimal", "low", "high", "xhigh"])]}
FAKE = r"""#!/usr/bin/env bash
echo "%s $1" >> "$HOME/verbs.log"
case $1 in
  install) : > "$HOME/bin/%s" && chmod +x "$HOME/bin/%s" ;;
  login) [ -t 0 ] && [ -t 1 ] && echo "<%s login on the terminal>" ;;
esac
exit 0
"""
CHILD = r"""
import os, shutil, sys
sys.path.insert(0, os.environ["MATRIX_REPO"])
from contextlib import closing
from pathlib import Path
from agentkit import config, menu, terminal, update

home = Path(os.environ["HOME"])
(home / "bin").mkdir()
(home / "adapters").mkdir()
for harness, program in %r.items():
    fake = home / "adapters" / f"{harness}.sh"
    fake.write_text(%r %% (harness, program, program, harness))
    fake.chmod(0o755)
(home / "bin" / "codex").touch(0o755)            # Codex is here already; Grok is not
os.environ["AGENTKIT_ADAPTER_DIR"] = str(home / "adapters")
config.harness_binary = lambda name: shutil.which(name, path=str(home / "bin")) or ""
config.catalog = lambda harness, cfg=None: [{"id": model, "label": label, "efforts": efforts}
                                  for model, label, efforts in %r.get(harness, [])]
update.version = lambda harness: ""
update.agentkit_version = lambda: "abc1234"
update.agentkit_newer = lambda: ""
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard)
print("<left>", flush=True)
""" % (PROGRAMS, FAKE, CATALOG)
ONE = """
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
SHIPPED = tomllib.loads((REPO / "config.default.toml").read_text())
MATRIX, PAGE = "agentkit · config", "agentkit · config · subscriptions"
ADD = "agentkit · config · add a subscription"
# the key line on every page and list, and under a question; `r` and `a` on new seats' matrix
KEYS = {"row": "  ↑↓←→ move   ⏎ open   r recommended   a apply to all sessions   esc back",
        "list": "  ↑↓←→ move   ⏎ choose   esc back", "ask": "  esc back"}
GIVE, TAKE = "\x1b[?1049l", "\x1b[?1049h"


def title(lines):
    """The screen's name on the header line, the clock off it."""
    return lines[0].rsplit(" ", 1)[0].strip()


def providers(lines):
    """The subscriptions whose meters are over the page, by name."""
    return sorted(name.strip() for line in lines[2:headings(lines)] if "—" in line
                  for name in line.split("— no reading yet") if name.strip())


def subscriptions(lines):
    """The subscriptions `Subscriptions` lists, by name, as its rows are drawn."""
    rows = lines[2:next(number for number, line in enumerate(lines)
                        if line[2:] == "+ add a subscription")]
    return [re.split(r"\s{2,}", line[2:])[0] for line in rows   # no heading, nor a row's line
            if line[:1] in " ›" and line[2:3].strip()]


def fresh(provider, saved):
    """`provider`'s shipped table, listing the one account its added login was made under: a
    new name, never the usual login's."""
    [account] = saved["providers"][provider]["accounts"]
    assert account != config.DEFAULT_ACCOUNT, account
    return {**SHIPPED["providers"][provider], "accounts": [account]}


def named(lines):
    """The name on the highlighted row of `Subscriptions`."""
    return re.split(r"\s{2,}", highlighted(lines)[2:])[0]


def open_page(screen):
    """Down the matrix to `Subscriptions` and into it: its page."""
    lines = screen.frame()
    for _ in range(20):
        if "› Subscriptions" in lines:          # no `›` while a meter is lit
            # a phone wraps the key line in two
            screen.case.assertTrue(" ".join(" ".join(lines[-2:]).split()).endswith(
                " ".join(KEYS["row"].split())), lines[-2:])
            return screen.press(ENTER, lambda lines: title(lines) == PAGE)
        lines = screen.press(DOWN)
    screen.case.fail(f"no `Subscriptions`: {lines}")


def open_row(screen, name):
    """`name`'s row on `Subscriptions`, from the matrix or the page: the page with it lit."""
    lines = screen.frame()
    lines = lines if title(lines) == PAGE else open_page(screen)
    for key in [UP] * 20 + [DOWN] * 20:
        if named(lines) == name:
            screen.case.assertEqual(lines[-1], KEYS["list"])
            return lines
        lines = screen.press(key)
    screen.case.fail(f"no row of {name}: {lines}")


def open_providers(screen):
    """`+ add a subscription` on `Subscriptions`, from the matrix or the page: the page with it
    lit."""
    return open_row(screen, "+ add a subscription")


def removing(screen, where):
    """`− remove` on the line the lit row of `Subscriptions` opens, last on it: the screen
    `where` accepts."""
    return screen.press(RIGHT * 3 + ENTER, where)


def remove_asked(screen, name):
    """`− remove` under `name`'s row on `Subscriptions`: the screen asking."""
    open_row(screen, name)
    return removing(screen, lambda lines: lines[-1] == KEYS["ask"])


def back(screen):
    """Esc from `Subscriptions` to the matrix: its screen."""
    return screen.press(ESC, lambda lines: title(lines) == MATRIX)


def choices(screen, after, count):
    """The `count` choices terminal.choose drew under its screen after `after`, as shown."""
    def ready(text):
        found = re.search(r"\x1b\[\d+;1H" + r"\r(.*?)\x1b\[K\r?\n" * count, text[after:])
        return found and [terminal.ANSI.sub("", part) for part in found.groups()]
    return screen.until(ready, f"{count} choices")


def pick(screen, keys, where, count):
    """`keys`, then the screen named `where` and the `count` choices listed on it."""
    mark = len(screen.text())
    lines = screen.press(keys, lambda lines: title(lines) == where)
    return lines, choices(screen, mark, count)


class ProviderScreen(unittest.TestCase):
    def test_adding_a_provider_installs_logs_in_then_adds_its_table_and_first_model(self):
        screen = Screen(self, child=CHILD, text=ONE)
        home = screen.path.parent.parent
        lines = open_providers(screen)
        self.assertEqual(subscriptions(lines), ["Claude"])
        lines, offered = pick(screen, ENTER, ADD, 6)
        self.assertEqual(lines[-1], KEYS["list"])
        self.assertEqual(offered[:3], ["› OpenAI / Codex", "  Meta / Muse", "  xAI / Grok Build"])
        mark = len(screen.text())
        lines = screen.press(DOWN * 2 + ENTER, lambda lines: title(lines) == PAGE)
        # install, because grok was nowhere; then login, on the terminal given back for it,
        # then whose login it is, for the line its row opens
        self.assertEqual((home / "verbs.log").read_text().split("\n"),
                         ["grokbuild install", "grokbuild login", "grokbuild login-end", ""])
        said = screen.text()[mark:]
        login = said.index("<grokbuild login on the terminal>")
        self.assertLess(said.index(GIVE), login)
        self.assertLess(login, said.index(TAKE, login))
        saved = screen.saved()
        self.assertEqual(saved["providers"]["xai"], fresh("xai", saved))
        # the first model its catalog lists, at the shipped `xhigh`, which Grok's own take
        self.assertEqual(saved["models"]["grok"], {"harness": "grokbuild", "model": "grok-mystery",
                                                   "effort": "xhigh", "provider": "xai"})
        self.assertEqual(saved["defaults"], {"orchestrator": "opus", "workers": ["opus"]})
        self.assertEqual(sorted(subscriptions(lines)), ["Claude", "Grok"])
        lines = back(screen)
        self.assertIn("Grok Build", lines)               # its harness, over its model
        self.assertEqual(providers(lines), ["Claude", "Grok"])
        # a program already there is logged in and never installed
        open_providers(screen)
        pick(screen, ENTER, ADD, 6)
        screen.press(ENTER,
                     lambda lines: title(lines) == PAGE and "ChatGPT" in subscriptions(lines))
        self.assertEqual((home / "verbs.log").read_text().split("\n")[3:],
                         ["codex login", "codex login-end", ""])
        saved = screen.saved()
        self.assertEqual(saved["providers"]["openai"], fresh("openai", saved))
        # under the name the shipped default gives it, whatever its catalog label
        self.assertEqual(saved["models"]["astra"], {"harness": "codex", "model": "gpt-7",
                                                    "effort": "xhigh", "provider": "openai"})
        back(screen)
        screen.leave()

    def test_an_added_provider_s_usage_model_names_the_model_it_added(self):
        screen = Screen(self, child=CHILD, text=ONE)
        open_providers(screen)
        pick(screen, ENTER, ADD, 6)
        screen.press(DOWN + ENTER,
                     lambda lines: title(lines) == PAGE and "Muse" in subscriptions(lines))
        saved = screen.saved()
        self.assertEqual(saved["providers"]["meta"], fresh("meta", saved))
        self.assertEqual(saved["models"]["spark"], {"harness": "muse", "model": "muse-spark-2",
                                                    "effort": "xhigh", "provider": "meta"})
        back(screen)
        screen.leave()
        # that name taken: nothing installed, logged in, added or written over
        spark = ('\n[models.spark]\nharness = "claude"\nmodel = "claude-sonnet-5"\n'
                 'effort = "high"\nprovider = "anthropic"\n')
        screen = Screen(self, child=CHILD, text=ONE + spark)
        open_providers(screen)
        before = screen.path.read_bytes()
        pick(screen, ENTER, ADD, 6)
        screen.press(DOWN + ENTER, lambda lines: "Meta / Muse adds its model as spark, and a "
                                                 "model has that name; nothing added" in lines[-3])
        self.assertEqual(screen.path.read_bytes(), before)
        back(screen)
        screen.leave()
        self.assertFalse((screen.path.parent.parent / "verbs.log").exists())

    def test_a_provider_already_added_is_not_offered(self):
        screen = Screen(self, child=CHILD, text=ONE)
        open_providers(screen)
        _, offered = pick(screen, ENTER, ADD, 6)
        self.assertEqual(offered, ["› OpenAI / Codex", "  Meta / Muse", "  xAI / Grok Build",
                                   "  Google / Antigravity", "  OpenCode", "  Claude II"])
        screen.press(ESC, lambda lines: title(lines) == PAGE)
        back(screen)
        screen.leave()
        # with every shipped provider added, OpenCode -- any provider it logs in to -- and
        # another subscription of each but MiMo, whose OpenCode keeps one login, are offered
        screen = Screen(self, child=CHILD)
        open_providers(screen)
        before, mark = screen.path.read_bytes(), len(screen.text())
        _, offered = pick(screen, ENTER, ADD, 6)
        self.assertEqual(offered, ["› OpenCode", "  Claude II", "  ChatGPT II", "  Muse II",
                                   "  Grok II", "  Gemini II"])
        self.assertNotIn("MiMo II", screen.text()[mark:])
        screen.press(ESC, lambda lines: title(lines) == PAGE)
        back(screen)
        self.assertEqual(screen.path.read_bytes(), before)
        screen.leave()
        home = screen.path.parent.parent
        self.assertFalse((home / "verbs.log").exists())

    def test_a_subscription_s_row_asks_to_remove_it(self):
        screen = Screen(self, child=CHILD)
        before = screen.path.read_bytes()
        # every subscription has its row, and `− remove` under it asks, Enter keeping
        meters = providers(screen.frame())
        self.assertEqual(sorted(subscriptions(open_page(screen))), meters)
        asked = remove_asked(screen, "Grok")
        self.assertEqual((title(asked), asked[3]), ("agentkit · config · Grok",
                                                    "  Remove Grok and its models?"))
        lines = screen.press(ENTER, lambda lines: title(lines) == PAGE)
        self.assertEqual(screen.path.read_bytes(), before)
        # a click on Claude's row points at it, opening its line, and one on its `− remove`
        # asks for Claude
        def click(text):
            row, col = next((number, line.index(text) + 1) for number, line
                            in enumerate(lines, 1) if text in line)
            return b"\x1b[<0;%d;%dM\x1b[<0;%d;%dm" % (col, row, col, row)
        lines = screen.press(click("Claude"),
                             lambda lines: highlighted(lines).startswith("› Claude"))
        screen.press(click("− remove"),
                     lambda lines: "  Remove Claude and its models?" in lines)
        lines = screen.press(DOWN + ENTER, lambda lines: title(lines) == PAGE)
        self.assertNotIn("Claude", subscriptions(lines))
        self.assertNotIn("anthropic", screen.saved()["providers"])
        back(screen)
        screen.leave()

    def test_two_providers_of_one_name_are_told_apart(self):
        house = ('\n[models.house]\nharness = "claude"\nmodel = "claude-sonnet-5"\n'
                 'effort = "high"\nprovider = "claude"\n\n[providers.claude]\nmode = "payg"\n')
        screen = Screen(self, child=CHILD, text=ONE + house)
        self.assertEqual(providers(screen.frame()), ["Claude", "Claude"])
        self.assertEqual(subscriptions(open_page(screen)), ["Claude", "Claude"])
        screen.press(DOWN)                  # the second, as its meter is the second
        removing(screen, lambda lines: "  Remove Claude and its models?" in lines)
        screen.press(DOWN + ENTER, lambda lines: title(lines) == PAGE)
        saved = screen.saved()
        self.assertEqual(list(saved["providers"]), ["anthropic"])
        self.assertEqual(list(saved["models"]), ["opus"])
        back(screen)
        screen.leave()

    def test_the_menu_s_probe_goes_on_with_the_providers_the_screen_left(self):
        before = SHIPPED
        left = config.remove_provider(copy.deepcopy(before), "meta")
        made = []

        class Kept(menu.Live):      # the probe it would start, never started: stdin is no tty
            def __init__(self, cfg, every=None):
                super().__init__(cfg, every)
                made.append(self)
        # its looks and its watch go on in threads, and read this HOME's runs and state
        with tempfile.TemporaryDirectory(prefix="provider-home-") as home, \
                mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch.multiple(config, **{name: Path(home) / name.lower() for name in (
                    "HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE")}), \
                mock.patch.object(sys, "stdin", io.StringIO()), \
                mock.patch.object(menu, "Live", Kept), \
                mock.patch.object(menu, "draw", return_value=(0, 1)), \
                mock.patch.object(menu.orch, "listing", return_value=[]), \
                mock.patch.object(menu.orch, "job_notices", return_value=[]), \
                menu_input(side_effect=["c", ""]), \
                mock.patch.object(menu, "show_config", return_value=left):
            self.assertEqual(menu.loop(before, dry_run=True), 0)
            made[0].watcher.join()          # its last look at state is this HOME's too
        self.assertIs(made[0].cfg, left)

    def test_a_removed_provider_takes_its_models_and_its_usage_row(self):
        screen = Screen(self, child=CHILD)
        remove_asked(screen, "Claude")
        screen.press(DOWN + ENTER, lambda lines: title(lines) == PAGE)
        lines = back(screen)
        self.assertNotIn("Claude", lines)
        for name in ("fable", "opus", "haiku"):
            self.assertFalse(any(line[2:].startswith(f"{name} ") for line in lines), name)
        self.assertEqual(providers(lines), ["ChatGPT", "Gemini", "Grok", "MiMo", "Muse"])
        saved = screen.saved()
        self.assertNotIn("anthropic", saved["providers"])
        self.assertFalse({"fable", "opus", "haiku"} & set(saved["models"]))
        # [defaults] passes over its models: the first model left takes the orchestrator's place
        self.assertEqual(saved["defaults"], {"orchestrator": "astra", "workers": ["astra"]})
        screen.leave()
        # the menu's usage rows are the providers the config has, read from this HOME's file
        home = screen.path.parent.parent / ".agentkit"
        with tempfile.TemporaryDirectory(prefix="provider-state-") as state, \
                mock.patch.object(config, "HOME", home), \
                mock.patch.object(config, "STATE", Path(state)):
            labels = [label for _, label, _, _ in menu.usage_cells(config.load())]
        self.assertEqual(len(labels), 5)
        self.assertIn("ChatGPT", labels)
        self.assertNotIn("Claude", labels)

    def test_a_free_provider_goes_with_its_last_model_and_one_left_bare_never_loads(self):
        free = '\n[providers.opencode]\nmode = "free"\nname = "OpenCode"\n'
        zeta = ('\n[models.zeta]\nharness = "opencode"\nmodel = "opencode/zeta-free"\n'
                'effort = "none"\nprovider = "opencode"\n')
        with tempfile.TemporaryDirectory(prefix="provider-free-") as home, \
                mock.patch.object(config, "HOME", Path(home)):
            path = Path(home) / config.CONFIG_NAME
            path.write_text(ONE + free + zeta)
            self.assertEqual(list(config.remove_model(config.load(), "zeta")["providers"]),
                             ["anthropic"])
            path.write_text(ONE + free + "\n[models.draft]\n")     # an older removal's, say
            self.assertEqual(list(config.load()["providers"]), ["anthropic"])

    def test_draft_provider_values_do_not_break_loading(self):
        with tempfile.TemporaryDirectory(prefix="config-draft-") as home, \
                mock.patch.object(config, "HOME", Path(home)):
            path = Path(home) / config.CONFIG_NAME
            for extra in ("", '\n[providers.acme]\nmode = "free"\n'):
                for value in ('["acme"]', '{name = "acme"}'):
                    with self.subTest(free=bool(extra), provider=value):
                        path.write_text(ONE + extra + "\n[models.draft]\nprovider = " + value + "\n")
                        cfg = config.load()
                        self.assertEqual(config.offered(cfg), ["opus"])
                        self.assertIn("draft", cfg["models"])
                        self.assertEqual(list(cfg["providers"]), ["anthropic"])

    def test_the_last_provider_stays(self):
        screen = Screen(self, child=CHILD, text=ONE)
        open_row(screen, "Claude")
        before, mark = screen.path.read_bytes(), len(screen.text())
        removing(screen, lambda lines: "the config needs one provider" in lines[-3])
        self.assertNotIn("and its models?", screen.text()[mark:])      # nothing asked
        self.assertEqual(screen.path.read_bytes(), before)
        back(screen)
        screen.leave()
        self.assertEqual(list(screen.saved()["providers"]), ["anthropic"])

    def test_a_phone_draws_the_row_and_the_add_step_in_forty_columns(self):
        screen = Screen(self, child=CHILD, rows=24, cols=40)
        lines = screen.frame()
        self.assertEqual(providers(lines), ["ChatGPT", "Claude", "Gemini", "Grok", "MiMo", "Muse"])
        for line in lines + open_providers(screen):
            self.assertLessEqual(terminal.cells(line), 40, line)
        back(screen)
        screen.leave()
        screen = Screen(self, child=CHILD, text=ONE, rows=24, cols=40)
        open_providers(screen)
        lines, offered = pick(screen, ENTER, "agentkit · config · add a subscri…", 6)   # cut
        for line in lines + offered:
            self.assertLessEqual(terminal.cells(line), 40, line)
        self.assertEqual(offered[-2], "  OpenCode")
        screen.press(ESC, lambda lines: title(lines) == PAGE)
        back(screen)
        screen.leave()


if __name__ == "__main__":
    unittest.main()
