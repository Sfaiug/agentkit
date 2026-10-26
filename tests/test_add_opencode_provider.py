"""`+ add a subscription` offers OpenCode, then every model OpenCode runs now, as its own
`/models` lists them, and after them every provider it can log in to; a picked provider is logged
in on the terminal and its models join the list.  A model and an effort picked are added with the
provider's table -- the shipped one where the shipped default has it, else the mode OpenCode's
prices say, under the name OpenCode gives it, but its own provider's, which is OpenCode -- so
nothing is typed into ak but what `/` finds in a list.  No second OpenCode login is offered: it
keeps one.

Each test runs `menu.show_config` with a real `terminal.Keyboard` in a child process on a pty of
its own, through tests/test_config_matrix.py's Screen, in a temporary HOME.  OpenCode's adapter
is a fake there: it logs each verb with the provider it was named, `install` puts an empty
program in a bin dir of the HOME's own, `login` on the terminal marks that provider logged in,
and `providers` lists `opencode` (OpenCode's own, which it calls OpenCode Console, free),
`zeta`, `mimo`, `anthropic` and `openai` by that mark.  The catalog is faked
too.  Nothing reads or writes the owner's ~/.agentkit or OpenCode's own home.
"""

import re
import unittest
from unittest import mock

from test_config_matrix import DOWN, ENTER, ESC, Screen, highlighted
from test_provider_screen import (ADD, GIVE, ONE, PAGE, SHIPPED, TAKE, back, open_providers, pick,
                                  providers, subscriptions, title)
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
THROUGH = ADD + " · OpenCode"


def listed(lines):
    """The open step's choices as drawn, each one's columns."""
    return [re.split(r"\s{2,}", line[4:].strip()) for line in lines[2:]
            if re.match(r"[ ›]   \S", line)]


def through(screen):
    """`+ add`, then OpenCode: the screen once its models and providers are listed."""
    open_providers(screen)
    _, offered = pick(screen, ENTER, ADD, 6)
    screen.case.assertEqual(offered[4], "  OpenCode")
    return screen.press(DOWN * 4 + ENTER, lambda lines: title(lines) == THROUGH
                        and "  model" in lines and listed(lines))


def verbs(screen):
    return (screen.path.parent.parent / "verbs.log").read_text().splitlines()


class AddOpenCodeProvider(unittest.TestCase):
    def test_a_provider_is_logged_in_then_its_model_added_at_its_own_mode(self):
        screen = Screen(self, child=CHILD, text=ONE)
        lines = through(screen)
        # installed, since its program was nowhere; the models it runs now, then the rest
        self.assertEqual(verbs(screen), ["opencode install ", "opencode providers "])
        self.assertEqual(listed(lines), [["Rocket 1", "OpenCode"], ["Zeta Free", "OpenCode"],
                                         ["Zeta Cloud", "zeta", "log in"],
                                         ["MiMo", "mimo", "log in"],
                                         ["Anthropic", "anthropic", "log in"],
                                         ["OpenAI", "openai", "log in"]])
        # `/` finds in the list: what is typed after it, in a name or an id
        lines = screen.press(b"/clo", lambda lines: "  model  /clo" in lines)
        self.assertEqual(listed(lines), [["Zeta Cloud", "zeta", "log in"]])
        mark = len(screen.text())
        lines = screen.press(ENTER, lambda lines: "  model" in lines and "Comet 2" in str(lines))
        # logged in on the terminal given back for it, then asked again: its model joins the
        # list, highlighted
        self.assertEqual(verbs(screen)[2:], ["opencode login zeta", "opencode providers "])
        said = screen.text()[mark:]
        login = said.index("<opencode login on the terminal>")
        self.assertLess(said.index(GIVE), login)
        self.assertLess(login, said.index(TAKE, login))
        self.assertEqual(listed(lines)[2], ["Comet 2", "Zeta Cloud"])
        self.assertTrue(highlighted(lines).startswith("›   Comet 2"), lines)
        lines = screen.press(ENTER, lambda lines: "  effort" in lines)
        self.assertIn("  model   Comet 2 · Zeta Cloud", lines)
        self.assertEqual(listed(lines), [["none"]])
        screen.press(ENTER, lambda lines: title(lines) == PAGE)
        lines = back(screen)
        # by the name OpenCode gives it on its meter, its model under OpenCode
        self.assertEqual(providers(lines), ["Claude", "Zeta Cloud"])
        shown = [line.strip() for line in lines]
        self.assertTrue(shown[shown.index("OpenCode") + 1].startswith("comet-2"), lines)
        saved = screen.saved()
        # priced by OpenCode: pay as you go, used only once every subscription runs ahead
        self.assertEqual(saved["providers"]["zeta"], {"mode": "payg", "name": "Zeta Cloud"})
        self.assertEqual(saved["models"]["comet"], {"harness": "opencode", "model": "zeta/comet-2",
                                                    "effort": "none", "provider": "zeta"})
        self.assertEqual(saved["defaults"], {"orchestrator": "opus", "workers": ["opus"]})
        screen.leave()

    def test_opencode_s_own_model_adds_with_no_login_under_its_name_and_no_second_login(self):
        screen = Screen(self, child=CHILD, text=ONE)
        through(screen)
        # a model's name finds it first, before the provider of that name that needs a login:
        # OpenCode's own free DeepSeek beside DeepSeek's paid one
        lines = screen.press(b"/zeta", lambda lines: "  model  /zeta" in lines)
        self.assertEqual(listed(lines), [["Zeta Free", "OpenCode"],
                                         ["Zeta Cloud", "zeta", "log in"]])
        screen.press(ENTER, lambda lines: "  effort" in lines)
        screen.press(ENTER, lambda lines: title(lines) == PAGE)
        through(screen)
        screen.press(ENTER, lambda lines: "  effort" in lines)
        screen.press(DOWN + ENTER, lambda lines: title(lines) == PAGE)
        self.assertNotIn("opencode login opencode", verbs(screen))
        saved = screen.saved()
        # OpenCode's own provider, by the harness's name rather than the one OpenCode gives it
        self.assertEqual(saved["providers"]["opencode"], {"mode": "free", "name": "OpenCode"})
        self.assertEqual(saved["models"]["zeta-free"], {
            "harness": "opencode", "model": "opencode/zeta-free", "effort": "none",
            "provider": "opencode"})
        self.assertEqual(saved["models"]["rocket"]["effort"], "max")
        # MiMo is shipped: its table as it ships, whose mode its endpoint says
        lines = through(screen)
        self.assertEqual(listed(lines)[1][:2], ["Zeta Free", "OpenCode"])   # marked as added
        screen.press(DOWN * 3 + ENTER, lambda lines: "MiMo V2.6 Pro" in str(lines))
        screen.press(ENTER, lambda lines: "  effort" in lines)
        screen.press(ENTER, lambda lines: title(lines) == PAGE)
        self.assertEqual(screen.saved()["providers"]["mimo"], SHIPPED["providers"]["mimo"])
        # no meter for OpenCode's own models, which are free; `+ add` offers it again, and no
        # second login of a provider on it, since it keeps one
        lines = open_providers(screen)
        self.assertEqual(sorted(subscriptions(lines)), ["Claude", "MiMo"])
        mark = len(screen.text())
        _, offered = pick(screen, ENTER, ADD, 6)
        self.assertEqual(offered[4:], ["  OpenCode", "  Claude II"])
        for name in ("OpenCode II", "MiMo II"):
            self.assertNotIn(name, screen.text()[mark:])
        screen.press(ESC, lambda lines: title(lines) == PAGE)
        back(screen)
        screen.leave()

    def test_the_name_an_older_add_gave_opencode_s_own_provider_reads_and_saves_as_opencode(self):
        older = ONE + ('\n[providers.opencode]\nmode = "subscription"\nname = "OpenCode Console"\n'
                       '\n[models.rocket]\nharness = "opencode"\nmodel = "opencode/rocket-1"\n'
                       'effort = "high"\nprovider = "opencode"\n')
        screen = Screen(self, child=CHILD, text=older)
        self.assertEqual(sorted(subscriptions(open_providers(screen))), ["Claude", "OpenCode"])
        lines = through(screen)
        self.assertEqual(listed(lines)[1][:2], ["Zeta Free", "OpenCode"])
        screen.press(DOWN + ENTER, lambda lines: "  effort" in lines)
        screen.press(ENTER, lambda lines: title(lines) == PAGE)
        self.assertEqual(screen.saved()["providers"]["opencode"],
                         {"mode": "subscription", "name": "OpenCode"})
        back(screen)
        screen.leave()

    def test_a_model_opencode_pays_for_stays_payg_whatever_its_provider_table_says(self):
        screen = Screen(self, child=CHILD, text=ONE)
        for provider in ("anthropic", "openai"):          # each logged in on a paid key
            (screen.path.parent.parent / f"in-{provider}").touch()
        # Claude's table the config holds, then Codex's as it ships: their plans pay for no
        # call OpenCode makes
        for at in (2, 3):
            through(screen)
            screen.press(DOWN * at + ENTER, lambda lines: "  effort" in lines)
            screen.press(ENTER, lambda lines: title(lines) == PAGE)
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
        back(screen)
        screen.leave()

    def test_esc_lets_a_find_go_then_goes_back_with_nothing_added(self):
        screen = Screen(self, child=CHILD, text=ONE, rows=9)
        before = screen.path.read_bytes()
        # a list longer than the screen says it can be found in
        self.assertEqual(through(screen)[-1], "  ↑↓←→ move   ⏎ choose   / find   esc back")
        lines = screen.press(b"/zz", lambda lines: "nothing here holds zz" in lines[-3])
        self.assertEqual(listed(lines), [])
        lines = screen.press(ESC, lambda lines: "  model" in lines and "/ find" in lines[-1])
        # a click on `/ find` finds as `/` does
        screen.click(lines[-1].index("/ find") + 1, len(lines),
                     lambda lines: "  model  /" in lines)
        screen.press(ESC, lambda lines: "  model" in lines and "/ find" in lines[-1])
        screen.press(ESC, lambda lines: title(lines) == PAGE)
        self.assertEqual(screen.path.read_bytes(), before)
        back(screen)
        screen.leave()


if __name__ == "__main__":
    unittest.main()
