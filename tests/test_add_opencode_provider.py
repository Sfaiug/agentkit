"""`Models` on `c` always has a row for OpenCode, which runs any provider it can log in to: Enter
installs it where its program is missing, then lists every model it runs now beside its
provider's name, as its own `/models` does, and after them `log in to <provider>` for every
provider it can log in to and has not, whose Enter logs it in on the terminal and lists again.
A model ticked in goes in with its provider's table where the config has none -- the shipped
one where the shipped default has it, else the mode OpenCode's prices say, under the name
OpenCode gives it, but its own provider's, which is OpenCode -- so nothing is typed into ak.
The owner (20 Oct 2026): "in opencode I am unabel to chose a model such as gpt".

Each test runs `menu.show_config` with a real `terminal.Keyboard` in a child process on a pty of
its own, through tests/test_config_matrix.py's Screen, in a temporary HOME.  OpenCode's adapter
is a fake there: it logs each verb with the provider it was named, `install` puts an empty
program in a bin dir of the HOME's own, `login` on the terminal marks that provider logged in,
and `providers` lists `opencode` (OpenCode's own, which it calls OpenCode Console, free),
`zeta`, `mimo`, `anthropic` and `openai` by that mark.  The catalog is faked
too.  Nothing reads or writes the owner's ~/.agentkit or OpenCode's own home.
"""

import unittest
from unittest import mock

from test_config_matrix import DOWN, ENTER, ESC, UP, Screen, highlighted
from test_provider_screen import (GIVE, MATRIX, ONE, SHIPPED, TAKE, back, open_page, providers,
                                  subscriptions, title)
from agentkit import matrix, usage

FAKE = r"""#!/usr/bin/env bash
echo "opencode $1 ${AGENTKIT_PROVIDER-}" >> "$HOME/verbs.log"
rows=("opencode"$'\t'"OpenCode Console"$'\t'"free" "zeta"$'\t'"Zeta Cloud"$'\t'"payg"
      "mimo"$'\t'"MiMo"$'\t'"payg" "anthropic"$'\t'"Anthropic"$'\t'"payg"
      "openai"$'\t'"OpenAI"$'\t'"payg")
case $1 in
  install) : > "$HOME/bin/opencode" && chmod +x "$HOME/bin/opencode" ;;
  login) [ -t 0 ] && echo "<opencode login on the terminal>" && : > "$HOME/in-$AGENTKIT_PROVIDER" ;;
  providers)
    for row in "${rows[@]}"; do [ -e "$HOME/in-${row%%$'\t'*}" ] && printf '%s\n' "$row"; done
    for row in "${rows[@]}"; do
      [ -e "$HOME/in-${row%%$'\t'*}" ] || printf '%s\t\n' "${row%$'\t'*}"
    done ;;
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
(home / "in-opencode").touch()
fake = home / "adapters" / "opencode.sh"
fake.write_text(%r)
fake.chmod(0o755)
os.environ["AGENTKIT_ADAPTER_DIR"] = str(home / "adapters")
config.harness_binary = lambda name: shutil.which(name, path=str(home / "bin")) or ""
config.catalog = lambda harness: [
    {"id": "opencode/rocket-1", "label": "Rocket 1", "efforts": ["high", "max"]},
    {"id": "opencode/zeta-free", "label": "Zeta Free", "efforts": ["none"]},
    {"id": "zeta/comet-2", "label": "Comet 2", "efforts": ["none"]},
    {"id": "mimo/mimo-v2.6-pro", "label": "MiMo V2.6 Pro", "efforts": ["none", "high"]},
    {"id": "anthropic/lyra-1", "label": "Lyra 1", "efforts": ["high"]},
    {"id": "openai/vega-1", "label": "Vega 1", "efforts": ["high"]}]
update.version = lambda harness: ""
update.agentkit_version = lambda: "abc1234"
update.agentkit_newer = lambda: ""
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard)
print("<left>", flush=True)
""" % (FAKE,)
MODELS = "agentkit · config · models"


def choices(lines):
    """The open list's choices, as drawn."""
    return [line[4:] for line in lines[2:] if line[:4] in ("    ", "›   ") and line[4:5] != " "]


def opencode(screen):
    """`Models`, from wherever `c`'s highlight is, then Enter on OpenCode's row: the screen once
    its list is drawn."""
    lines = screen.frame()
    for key in [DOWN] * 20 + [UP] * 20:         # up from the first model lights a meter
        if "› Models" in lines:
            break
        lines = screen.press(key)
    lines = screen.press(ENTER, lambda lines: title(lines) == MODELS)
    screen.case.assertTrue(any(line.startswith("  OpenCode ") for line in lines), lines)
    while not highlighted(lines).startswith("› OpenCode"):
        lines = screen.press(DOWN)
    return screen.press(ENTER, lambda lines: any("log in to" in line for line in lines))


def choose(screen, choice, until):
    """The highlight walked onto `choice`, then Enter: the screen once `until(lines)`."""
    lines = screen.frame()
    for key in [UP] * 9 + [DOWN] * 9:
        if highlighted(lines)[4:] == choice:
            return screen.press(ENTER, until)
        lines = screen.press(key)
    screen.case.fail(f"no {choice}: {lines}")


def leave(screen):
    """Esc from the list, the page and `c`'s matrix: its screen."""
    return screen.press(ESC + ESC, lambda lines: title(lines) == MATRIX)


def verbs(screen):
    return (screen.path.parent.parent / "verbs.log").read_text().splitlines()


class OpenCodeModels(unittest.TestCase):
    def test_a_provider_is_logged_in_then_its_model_ticked_in_at_its_own_mode(self):
        screen = Screen(self, child=CHILD, text=ONE)
        lines = opencode(screen)
        # installed, since its program was nowhere; the models it runs now, then the rest
        self.assertEqual(verbs(screen), ["opencode install ", "opencode providers "])
        self.assertEqual(choices(lines), ["□ Rocket 1 OpenCode", "□ Zeta Free OpenCode",
                                          "log in to Zeta Cloud", "log in to MiMo",
                                          "log in to Anthropic", "log in to OpenAI"])
        mark = len(screen.text())
        lines = choose(screen, "log in to Zeta Cloud", lambda lines: "□ Comet 2 Zeta Cloud"
                       in choices(lines))
        # logged in on the terminal given back for it, then asked again: its model is listed
        self.assertEqual(verbs(screen)[2:], ["opencode login zeta", "opencode providers "])
        said = screen.text()[mark:]
        login = said.index("<opencode login on the terminal>")
        self.assertLess(said.index(GIVE), login)
        self.assertLess(login, said.index(TAKE, login))
        self.assertNotIn("log in to Zeta Cloud", choices(lines))
        choose(screen, "□ Comet 2 Zeta Cloud",
               lambda lines: "■ Comet 2 Zeta Cloud" in choices(lines))
        saved = screen.saved()
        # priced by OpenCode: pay as you go, used only once every subscription runs ahead
        self.assertEqual(saved["providers"]["zeta"], {"mode": "payg", "name": "Zeta Cloud"})
        self.assertEqual(saved["models"]["comet"], {"harness": "opencode", "model": "zeta/comet-2",
                                                    "effort": "none", "provider": "zeta"})
        self.assertEqual(saved["defaults"], {"orchestrator": "opus", "workers": ["opus"]})
        # by the name OpenCode gives it, on its meter and on OpenCode's row
        screen.press(ESC, lambda lines: ["›", "OpenCode", "comet-2"] in map(str.split, lines))
        self.assertEqual(providers(back(screen)), ["Claude", "Zeta Cloud"])
        screen.leave()

    def test_opencode_s_own_model_needs_no_login_and_a_shipped_provider_comes_as_it_ships(self):
        screen = Screen(self, child=CHILD, text=ONE)
        opencode(screen)
        choose(screen, "□ Zeta Free OpenCode",
               lambda lines: "■ Zeta Free OpenCode" in choices(lines))
        saved = screen.saved()
        # OpenCode's own provider, by the harness's name rather than the one OpenCode gives it
        self.assertEqual(saved["providers"]["opencode"], {"mode": "free", "name": "OpenCode"})
        self.assertEqual(saved["models"]["zeta-free"], {
            "harness": "opencode", "model": "opencode/zeta-free", "effort": "none",
            "provider": "opencode"})
        # MiMo is shipped: its table as it ships
        choose(screen, "log in to MiMo", lambda lines: "□ MiMo V2.6 Pro MiMo" in choices(lines))
        choose(screen, "□ MiMo V2.6 Pro MiMo",
               lambda lines: "■ MiMo V2.6 Pro MiMo" in choices(lines))
        self.assertNotIn("opencode login opencode", verbs(screen))
        self.assertEqual(screen.saved()["providers"]["mimo"], SHIPPED["providers"]["mimo"])
        leave(screen)
        # no meter for OpenCode's own models, which are free
        self.assertEqual(sorted(subscriptions(open_page(screen))), ["Claude", "MiMo"])
        back(screen)
        screen.leave()

    def test_the_name_an_older_add_gave_opencode_s_own_provider_reads_and_saves_as_opencode(self):
        older = ONE + ('\n[providers.opencode]\nmode = "subscription"\nname = "OpenCode Console"\n'
                       '\n[models.rocket]\nharness = "opencode"\nmodel = "opencode/rocket-1"\n'
                       'effort = "high"\nprovider = "opencode"\n')
        screen = Screen(self, child=CHILD, text=older)
        self.assertEqual(sorted(subscriptions(open_page(screen))), ["Claude", "OpenCode"])
        back(screen)
        lines = opencode(screen)
        self.assertEqual(highlighted(lines)[4:], "■ Rocket 1 OpenCode")
        choose(screen, "□ Zeta Free OpenCode",
               lambda lines: "■ Zeta Free OpenCode" in choices(lines))
        self.assertEqual(screen.saved()["providers"]["opencode"],
                         {"mode": "subscription", "name": "OpenCode"})
        leave(screen)
        screen.leave()

    def test_a_model_opencode_pays_for_stays_payg_whatever_its_provider_table_says(self):
        screen = Screen(self, child=CHILD, text=ONE)
        for provider in ("anthropic", "openai"):          # each logged in on a paid key
            (screen.path.parent.parent / f"in-{provider}").touch()
        opencode(screen)
        # Claude's table the config holds, then Codex's as it ships: their plans pay for no
        # call OpenCode makes
        for model in ("Lyra 1 Anthropic", "Vega 1 OpenAI"):
            choose(screen, f"□ {model}", lambda lines: f"■ {model}" in choices(lines))
        saved = screen.saved()
        self.assertEqual(saved["providers"]["anthropic"], {"mode": "subscription"})
        self.assertEqual(saved["providers"]["openai"], SHIPPED["providers"]["openai"])
        self.assertEqual(saved["models"]["lyra"], {
            "harness": "opencode", "model": "anthropic/lyra-1", "effort": "high",
            "provider": "anthropic", "mode": "payg"})
        self.assertEqual(saved["models"]["vega"]["mode"], "payg")
        # so neither is picked while a subscription runs behind pace; no rank is read off disk
        with mock.patch.object(matrix, "rank", return_value={}):
            self.assertEqual(usage.pick_order(saved, {}, list(saved["models"]), quiet=True),
                             ["opus"])
        leave(screen)
        screen.leave()


if __name__ == "__main__":
    unittest.main()
