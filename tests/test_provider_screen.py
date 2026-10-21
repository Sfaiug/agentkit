"""`+ add a provider` in `c` adds a provider the way it ships and a meter removes one: `+ add`
offers the shipped default's providers the config has not, installs the picked one's harness when
its program is missing, logs it in on the terminal, then adds its shipped table and its first
catalog model; a meter's `− remove` asks with `Keep` picked and takes its models, the last
provider stays, and a free provider, which has no meter, goes with its last model.

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

from test_config_matrix import DOWN, ENTER, ESC, REPO, UP, Screen, headings, highlighted
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
# `c` from a heading, new seats' marks over the efforts
MATRIX, ADD = "agentkit · config · new seats", "agentkit · config · add a provider"
KEYS = {"row": "  ↑↓ move   ⏎ open   esc back", "add": "  ↑↓ move   ⏎ add   esc back",
        "choose": "  ↑↓ move   ⏎ choose   esc back", "ask": "  esc back"}
GIVE, TAKE = "\x1b[?1049l", "\x1b[?1049h"


def title(lines):
    """The screen's name on the header line, the clock off it."""
    return lines[0].rsplit(" ", 1)[0].strip()


def providers(lines):
    """The subscriptions whose meters are over the page, by name."""
    return sorted(name.strip() for line in lines[2:headings(lines)] if "—" in line
                  for name in line.split("— no reading yet") if name.strip())


def open_providers(screen):
    """Down the matrix to `+ add a provider`: the screen with it highlighted."""
    lines = screen.frame()
    for _ in range(20):
        if "› + add a provider" in lines:       # no `›` while a meter is lit
            screen.case.assertEqual(lines[-1], KEYS["row"])
            return lines
        lines = screen.press(DOWN)
    screen.case.fail(f"no `+ add a provider`: {lines}")


def open_meter(screen, name):
    """↑ onto `name`'s meter over the page, ↓ back if past it: the screen with it lit."""
    lines = screen.frame()
    for key in [UP] * 20 + [DOWN] * 10:
        if lines[headings(lines) - 1].strip().startswith(name + "  "):
            screen.case.assertEqual(lines[-1], KEYS["row"])
            return lines
        lines = screen.press(key)
    screen.case.fail(f"no meter of {name}: {lines}")


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
        self.assertEqual(providers(lines), ["Claude"])
        lines, offered = pick(screen, ENTER, ADD, 6)
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
        # the first model its catalog lists, at the shipped `xhigh`, which Grok's own take
        self.assertEqual(saved["models"]["grok"], {"harness": "grokbuild", "model": "grok-mystery",
                                                   "effort": "xhigh", "provider": "xai"})
        self.assertEqual(saved["defaults"], {"orchestrator": "opus", "workers": ["opus"]})
        self.assertIn("Grok Build", lines)               # its harness, over its model
        self.assertEqual(providers(lines), ["Claude", "Grok"])
        self.assertTrue(highlighted(lines).startswith("› + add a provider"))
        # a program already there is logged in and never installed
        pick(screen, ENTER, ADD, 6)
        screen.press(ENTER, lambda lines: title(lines) == MATRIX and "Codex" in lines)
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
        pick(screen, ENTER, ADD, 6)
        screen.press(DOWN + ENTER, lambda lines: title(lines) == MATRIX and "Muse Code" in lines)
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
        pick(screen, ENTER, ADD, 6)
        screen.press(DOWN + ENTER, lambda lines: "Meta / Muse adds its model as spark, and a "
                                                 "model has that name; nothing added" in lines[-3])
        self.assertEqual(screen.path.read_bytes(), before)
        screen.leave()
        self.assertFalse((screen.path.parent.parent / "verbs.log").exists())

    def test_a_provider_already_added_is_not_offered(self):
        screen = Screen(self, child=CHILD, text=ONE)
        open_providers(screen)
        _, offered = pick(screen, ENTER, ADD, 6)
        self.assertEqual(offered, ["› OpenAI / Codex", "  Meta / Muse", "  xAI / Grok Build",
                                   "  Google / Antigravity", "  OpenCode", "  Claude II"])
        screen.press(ESC, lambda lines: title(lines) == MATRIX)
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
        screen.press(ESC, lambda lines: title(lines) == MATRIX)
        self.assertEqual(screen.path.read_bytes(), before)
        screen.leave()
        home = screen.path.parent.parent
        self.assertFalse((home / "verbs.log").exists())

    def test_a_meter_is_reached_and_asks_to_remove_its_provider(self):
        screen = Screen(self, child=CHILD)
        before = screen.path.read_bytes()
        # ↑ past the first model lights the last meter, its line under the meters
        lines = screen.press(UP, lambda lines: lines[headings(lines) - 1].strip())
        name = lines[headings(lines) - 1].split()[0]
        self.assertEqual(lines[-1], "  ↑↓ move   ⏎ open   esc back")
        # `− remove` is all it offers, so it asks at once, and Enter keeps
        asked = screen.press(ENTER, lambda lines: lines[-1] == KEYS["ask"])
        self.assertEqual((title(asked), asked[3]), (f"agentkit · config · {name}",
                                                    f"  Remove {name} and its models?"))
        lines = screen.press(ENTER, lambda lines: title(lines) == MATRIX)
        self.assertEqual(screen.path.read_bytes(), before)
        # a click on Claude's meter, on the line it is drawn on, asks for Claude
        row = next(number for number, line in enumerate(lines, 1) if line.startswith("  Claude "))
        screen.press(b"\x1b[<0;4;%dM\x1b[<0;4;%dm" % (row, row),
                     lambda lines: "  Remove Claude and its models?" in lines)
        screen.press(DOWN + ENTER, lambda lines: title(lines) == MATRIX)
        self.assertNotIn("anthropic", screen.saved()["providers"])
        screen.leave()

    def test_two_providers_of_one_name_are_told_apart(self):
        house = ('\n[models.house]\nharness = "claude"\nmodel = "claude-sonnet-5"\n'
                 'effort = "high"\nprovider = "claude"\n\n[providers.claude]\nmode = "payg"\n')
        screen = Screen(self, child=CHILD, text=ONE + house)
        self.assertEqual(providers(screen.frame()), ["Claude", "Claude"])
        screen.press(UP + ENTER, lambda lines: "  Remove Claude and its models?" in lines)
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
                menu_input(side_effect=["c", ""]), \
                mock.patch.object(menu, "show_config", return_value=left):
            self.assertEqual(menu.loop(before, dry_run=True), 0)
            made[0].watcher.join()          # its last look at state is this HOME's too
        self.assertIs(made[0].cfg, left)

    def test_a_removed_provider_takes_its_models_and_its_usage_row(self):
        screen = Screen(self, child=CHILD)
        open_meter(screen, "Claude")
        screen.press(ENTER, lambda lines: "  Remove Claude and its models?" in lines)
        lines = screen.press(DOWN + ENTER, lambda lines: title(lines) == MATRIX)
        self.assertNotIn("Claude Code", lines)
        for name in ("fable", "opus", "haiku"):
            self.assertFalse(any(line[2:].startswith(f"{name} ") for line in lines), name)
        self.assertEqual(providers(lines), ["ChatGPT", "Gemini", "Grok", "MiMo", "Muse"])
        saved = screen.saved()
        self.assertNotIn("anthropic", saved["providers"])
        self.assertFalse({"fable", "opus", "haiku"} & set(saved["models"]))
        # [defaults] is the last creation's, and only a creation writes it
        self.assertEqual(saved["defaults"], {"orchestrator": "opus", "workers": ["opus", "astra"]})
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
        open_meter(screen, "Claude")
        before, mark = screen.path.read_bytes(), len(screen.text())
        screen.press(ENTER, lambda lines: "the config needs one provider" in lines[-3])
        self.assertNotIn("and its models?", screen.text()[mark:])      # nothing asked
        self.assertEqual(screen.path.read_bytes(), before)
        screen.leave()
        self.assertEqual(list(screen.saved()["providers"]), ["anthropic"])

    def test_a_phone_draws_the_row_and_the_add_step_in_forty_columns(self):
        screen = Screen(self, child=CHILD, rows=24, cols=40)
        lines = screen.frame()
        self.assertEqual(providers(lines), ["ChatGPT", "Claude", "Gemini", "Grok", "MiMo", "Muse"])
        for line in lines + open_providers(screen):      # the meters scroll off above the row
            self.assertLessEqual(terminal.cells(line), 40, line)
        screen.leave()
        screen = Screen(self, child=CHILD, text=ONE, rows=24, cols=40)
        open_providers(screen)
        lines, offered = pick(screen, ENTER, ADD, 6)
        for line in lines + offered:
            self.assertLessEqual(terminal.cells(line), 40, line)
        self.assertEqual(offered[-2], "  OpenCode")
        screen.press(ESC, lambda lines: title(lines) == MATRIX)
        screen.leave()


if __name__ == "__main__":
    unittest.main()
