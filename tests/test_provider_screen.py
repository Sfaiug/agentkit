"""`Providers` in `c` adds a provider the way it ships and removes one with its models: `+ add`
offers the shipped default's providers the config has not, installs the picked one's harness when
its program is missing, logs it in on the terminal, then adds its shipped table and its first
catalog model; `− remove` asks with `Keep` picked, and the last provider stays.

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

from test_config_matrix import DOWN, ENTER, ESC, REPO, RIGHT, Screen, highlighted
from agentkit import config, menu, terminal

PROGRAMS = {"claude": "claude", "codex": "codex", "muse": "muse", "grokbuild": "grok",
            "opencode": "opencode", "antigravity": "agy"}
# Grok's first entry says no efforts, so the model added is the one after it.
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
config.catalog = lambda harness: [{"id": model, "label": label, "efforts": efforts}
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
MATRIX, ADD, REMOVE = ("agentkit · config", "agentkit · config · add a provider",
                       "agentkit · config · remove a provider")
KEYS = {"row": "  ↑↓←→ move   ⏎ open   esc back", "add": "  ↑↓ move   ⏎ add   esc back",
        "choose": "  ↑↓ move   ⏎ choose   esc back", "ask": "  esc keep"}
GIVE, TAKE = "\x1b[?1049l", "\x1b[?1049h"


def title(lines):
    """The screen's name on the header line, the clock off it."""
    return lines[0].rsplit(" ", 1)[0].strip()


def providers(lines):
    """The Providers row as drawn, its first line from `Providers` on, and any line under it."""
    at = next(number for number, line in enumerate(lines) if line[2:].startswith("Providers"))
    shown = [lines[at][2:]]
    for line in lines[at + 1:]:
        if not line.startswith(" " * 17) or not line.strip():
            break
        shown.append(line.strip())
    return shown


def open_providers(screen):
    """Down the matrix to Providers: the screen with it highlighted, `+ add` its act."""
    lines = screen.frame()
    for _ in range(20):
        if highlighted(lines).startswith("› Providers"):
            screen.case.assertEqual(lines[-1], KEYS["row"])
            return lines
        lines = screen.press(DOWN)
    screen.case.fail(f"no Providers row: {lines}")


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
        self.assertEqual(providers(lines), ["Providers      Claude  + add  − remove"])
        lines, offered = pick(screen, ENTER, ADD, 5)
        self.assertEqual(lines[-1], KEYS["add"])
        self.assertEqual(offered[:3], ["› OpenAI / Codex", "  Meta / Muse", "  xAI / Grok Build"])
        mark = len(screen.text())
        lines = screen.press(DOWN * 2 + ENTER, lambda lines: title(lines) == MATRIX)
        # install, because grok was nowhere; then login, on the terminal given back for it
        self.assertEqual((home / "verbs.log").read_text().split("\n"),
                         ["grokbuild install", "grokbuild login", ""])
        said = screen.text()[mark:]
        login = said.index("<grokbuild login on the terminal>")
        self.assertLess(said.index(GIVE), login)
        self.assertLess(login, said.index(TAKE, login))
        saved = screen.saved()
        self.assertEqual(saved["providers"]["xai"], SHIPPED["providers"]["xai"])
        # the first model its catalog lists efforts for, at the shipped `xhigh`'s nearest
        self.assertEqual(saved["models"]["grok"], {"harness": "grokbuild", "model": "grok-5",
                                                   "effort": "high", "provider": "xai"})
        self.assertEqual(saved["defaults"], {"orchestrator": "opus", "workers": ["opus"]})
        self.assertIn("Grok", lines)
        self.assertEqual(providers(lines), ["Providers      Claude  Grok  + add  − remove"])
        self.assertTrue(highlighted(lines).startswith("› Providers"))
        # a program already there is logged in and never installed
        pick(screen, ENTER, ADD, 4)
        screen.press(ENTER, lambda lines: title(lines) == MATRIX and "ChatGPT" in lines)
        self.assertEqual((home / "verbs.log").read_text().split("\n")[2:], ["codex login", ""])
        saved = screen.saved()
        self.assertEqual(saved["providers"]["openai"], SHIPPED["providers"]["openai"])
        # under the name the shipped default gives it, whatever its catalog label
        self.assertEqual(saved["models"]["astra"], {"harness": "codex", "model": "gpt-7",
                                                    "effort": "xhigh", "provider": "openai"})
        screen.leave()

    def test_an_added_provider_s_usage_model_names_the_model_it_added(self):
        screen = Screen(self, child=CHILD, text=ONE)
        open_providers(screen)
        pick(screen, ENTER, ADD, 5)
        screen.press(DOWN + ENTER, lambda lines: title(lines) == MATRIX and "Muse" in lines)
        saved = screen.saved()
        self.assertEqual(saved["providers"]["meta"], SHIPPED["providers"]["meta"])
        self.assertEqual(saved["models"]["spark"], {"harness": "muse", "model": "muse-spark-2",
                                                    "effort": "xhigh", "provider": "meta"})
        screen.leave()
        # that name taken: nothing installed, logged in, added or written over
        spark = ('\n[models.spark]\nharness = "claude"\nmodel = "claude-sonnet-5"\n'
                 'effort = "high"\nprovider = "anthropic"\n')
        screen = Screen(self, child=CHILD, text=ONE + spark)
        open_providers(screen)
        before = screen.path.read_bytes()
        pick(screen, ENTER, ADD, 5)
        screen.press(DOWN + ENTER, lambda lines: "Meta / Muse adds its model as spark, and a "
                                                 "model has that name; nothing added" in lines[-3])
        self.assertEqual(screen.path.read_bytes(), before)
        screen.leave()
        self.assertFalse((screen.path.parent.parent / "verbs.log").exists())

    def test_a_provider_already_added_is_not_offered(self):
        screen = Screen(self, child=CHILD, text=ONE)
        open_providers(screen)
        _, offered = pick(screen, ENTER, ADD, 5)
        self.assertEqual(offered, ["› OpenAI / Codex", "  Meta / Muse", "  xAI / Grok Build",
                                   "  Google / Antigravity", "  Xiaomi / MiMo through OpenCode"])
        screen.press(ESC, lambda lines: title(lines) == MATRIX)
        screen.leave()
        # with every shipped provider added there is nothing to offer, and nothing is drawn
        screen = Screen(self, child=CHILD)
        open_providers(screen)
        before, mark = screen.path.read_bytes(), len(screen.text())
        lines = screen.press(ENTER, lambda lines: "every provider agentkit ships is added"
                                                  in lines[-3])
        self.assertNotIn("add a provider", screen.text()[mark:])
        self.assertEqual(screen.path.read_bytes(), before)
        screen.leave()
        home = screen.path.parent.parent
        self.assertFalse((home / "verbs.log").exists())

    def test_remove_asks_with_keep_preselected(self):
        screen = Screen(self, child=CHILD)
        open_providers(screen)
        mark = len(screen.text())
        lines = screen.press(RIGHT)
        screen.saw("\x1b[7m− remove", after=mark)          # reversed: the act Enter runs
        self.assertTrue(highlighted(lines).startswith("› Providers"))
        before = screen.path.read_bytes()
        lines, listed = pick(screen, ENTER, REMOVE, 6)
        self.assertEqual(listed, ["› Claude", "  ChatGPT", "  Muse", "  Grok", "  Gemini",
                                  "  MiMo"])
        self.assertEqual(lines[-1], KEYS["choose"])
        asked = screen.press(DOWN + ENTER, lambda lines: lines[-1] == KEYS["ask"])
        self.assertIn("  Remove ChatGPT and its models?", asked)
        self.assertFalse(any(line.startswith("›") for line in asked), asked)
        mark = screen.text().rindex("and its models?")          # the answers go under it
        self.assertEqual(choices(screen, mark, 2), ["› Keep", "  Remove"])
        lines = screen.press(ENTER, lambda lines: title(lines) == MATRIX)    # Enter keeps
        self.assertEqual(screen.path.read_bytes(), before)
        self.assertIn("ChatGPT", lines)
        pick(screen, ENTER, REMOVE, 6)
        screen.press(DOWN + ENTER, lambda lines: lines[-1] == KEYS["ask"])
        screen.press(ESC, lambda lines: title(lines) == MATRIX)              # so does Esc
        self.assertEqual(screen.path.read_bytes(), before)
        screen.leave()

    def test_two_providers_of_one_name_are_told_apart(self):
        house = ('\n[models.house]\nharness = "claude"\nmodel = "claude-sonnet-5"\n'
                 'effort = "high"\nprovider = "claude"\n\n[providers.claude]\nmode = "payg"\n')
        screen = Screen(self, child=CHILD, text=ONE + house)
        open_providers(screen)
        _, listed = pick(screen, RIGHT + ENTER, REMOVE, 2)
        self.assertEqual(listed, ["› Claude (anthropic)", "  Claude (claude)"])
        screen.press(DOWN + ENTER, lambda lines: "  Remove Claude (claude) and its models?"
                                                 in lines)
        screen.press(DOWN + ENTER, lambda lines: title(lines) == MATRIX)
        saved = screen.saved()
        self.assertEqual(list(saved["providers"]), ["anthropic"])
        self.assertEqual(list(saved["models"]), ["opus"])
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
                mock.patch.object(menu, "wait_key", side_effect=["c", "q"]), \
                mock.patch.object(menu, "read", return_value=""), \
                mock.patch.object(menu, "show_config", return_value=left):
            self.assertEqual(menu.loop(before, dry_run=True), 0)
            made[0].watcher.join()          # its last look at state is this HOME's too
        self.assertIs(made[0].cfg, left)

    def test_a_removed_provider_takes_its_models_and_its_usage_row(self):
        screen = Screen(self, child=CHILD)
        lines = open_providers(screen)
        row = next(number for number, line in enumerate(lines, 1) if "− remove" in line)
        col = terminal.cells(lines[row - 1].split("− remove")[0]) + 2
        pick(screen, b"\x1b[<0;%d;%dM\x1b[<0;%d;%dm" % (col, row, col, row), REMOVE, 6)
        screen.press(ENTER, lambda lines: "  Remove Claude and its models?" in lines)
        lines = screen.press(DOWN + ENTER, lambda lines: title(lines) == MATRIX)
        self.assertNotIn("Claude", lines)
        for name in ("fable", "opus", "haiku"):
            self.assertFalse(any(line[2:].startswith(f"{name} ") for line in lines), name)
        self.assertEqual(providers(lines),
                         ["Providers      ChatGPT  Muse  Grok  Gemini  MiMo  + add  − remove"])
        saved = screen.saved()
        self.assertNotIn("anthropic", saved["providers"])
        self.assertFalse({"fable", "opus", "haiku"} & set(saved["models"]))
        self.assertEqual(saved["defaults"], {"orchestrator": "astra", "workers": ["astra"]})
        screen.leave()
        # the menu's usage rows are the providers the config has, read from this HOME's file
        home = screen.path.parent.parent / ".agentkit"
        with tempfile.TemporaryDirectory(prefix="provider-state-") as state, \
                mock.patch.object(config, "HOME", home), \
                mock.patch.object(config, "STATE", Path(state)):
            rows = [terminal.ANSI.sub("", line) for line in menu.usage_lines(config.load(), 100)]
        self.assertEqual(len(rows), 1 + 5)
        self.assertTrue(any(line[2:].startswith("ChatGPT") for line in rows), rows)
        self.assertFalse(any("Claude" in line for line in rows), rows)

    def test_the_last_provider_stays(self):
        screen = Screen(self, child=CHILD, text=ONE)
        open_providers(screen)
        before, mark = screen.path.read_bytes(), len(screen.text())
        lines = screen.press(RIGHT + ENTER,
                             lambda lines: "the config needs one provider" in lines[-3])
        self.assertTrue(highlighted(lines).startswith("› Providers"))
        self.assertNotIn("and its models?", screen.text()[mark:])      # nothing asked
        self.assertEqual(screen.path.read_bytes(), before)
        screen.leave()
        self.assertEqual(list(screen.saved()["providers"]), ["anthropic"])

    def test_a_phone_draws_the_row_and_the_add_step_in_forty_columns(self):
        screen = Screen(self, child=CHILD, rows=24, cols=40)
        lines = open_providers(screen)
        self.assertEqual(providers(lines), ["Providers      Claude  ChatGPT  Muse",
                                            "Grok  Gemini  MiMo", "+ add  − remove"])
        for line in lines:
            self.assertLessEqual(terminal.cells(line), 40, line)
        screen.leave()
        screen = Screen(self, child=CHILD, text=ONE, rows=24, cols=40)
        open_providers(screen)
        lines, offered = pick(screen, ENTER, ADD, 5)
        for line in lines + offered:
            self.assertLessEqual(terminal.cells(line), 40, line)
        self.assertEqual(offered[-1], "  Xiaomi / MiMo through OpenCode")
        screen.press(ESC, lambda lines: title(lines) == MATRIX)
        screen.leave()


if __name__ == "__main__":
    unittest.main()
