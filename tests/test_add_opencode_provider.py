"""`+ add` on Providers offers OpenCode, then any provider OpenCode can log in to: the logged-in
ones first, a picked one with no login logged in on the terminal, then one of its models and an
effort, added with the provider's table -- the shipped one where the shipped default has it,
else the mode OpenCode's prices say -- so nothing is typed into ak.

Each test runs `menu.show_config` with a real `terminal.Keyboard` in a child process on a pty of
its own, through tests/test_config_matrix.py's Screen, in a temporary HOME.  OpenCode's adapter
is a fake there: it logs each verb with the provider it was named, `install` puts an empty
program in a bin dir of the HOME's own, `login` on the terminal marks that provider logged in,
and `providers` lists `acme` (logged in), `zeta` and `mimo` by that mark.  The catalog is faked
too.  Nothing reads or writes the owner's ~/.agentkit or OpenCode's own home.
"""

import unittest

from test_config_matrix import DOWN, ENTER, ESC, Screen
from test_add_model import listed
from test_provider_screen import GIVE, ONE, SHIPPED, TAKE, open_providers, pick, providers, title

FAKE = r"""#!/usr/bin/env bash
echo "opencode $1 ${AGENTKIT_PROVIDER-}" >> "$HOME/verbs.log"
rows=("acme"$'\t'"Acme Plan"$'\t'"subscription" "zeta"$'\t'"Zeta Cloud"$'\t'"payg"
      "mimo"$'\t'"MiMo"$'\t'"payg")
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
(home / "in-acme").touch()
fake = home / "adapters" / "opencode.sh"
fake.write_text(%r)
fake.chmod(0o755)
os.environ["AGENTKIT_ADAPTER_DIR"] = str(home / "adapters")
config.harness_binary = lambda name: shutil.which(name, path=str(home / "bin")) or ""
config.catalog = lambda harness: [
    {"id": "acme/rocket-1", "label": "Rocket 1", "efforts": ["high", "max"]},
    {"id": "zeta/comet-2", "label": "Comet 2", "efforts": ["none"]},
    {"id": "mimo/mimo-v2.6-pro", "label": "MiMo V2.6 Pro", "efforts": ["none", "high"]}]
update.version = lambda harness: ""
update.agentkit_version = lambda: "abc1234"
update.agentkit_newer = lambda: ""
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard)
print("<left>", flush=True)
""" % (FAKE,)
MATRIX, ADD = "agentkit · config", "agentkit · config · add a provider"
THROUGH = "agentkit · config · add a provider · OpenCode"


def through(screen):
    """`+ add`, then OpenCode: the screen once its providers are listed."""
    open_providers(screen)
    _, offered = pick(screen, ENTER, ADD, 6)
    screen.case.assertEqual(offered[4], "  OpenCode")
    return screen.press(DOWN * 4 + ENTER, lambda lines: title(lines) == THROUGH
                        and "  provider" in lines and listed(lines))


def verbs(screen):
    return (screen.path.parent.parent / "verbs.log").read_text().splitlines()


class AddOpenCodeProvider(unittest.TestCase):
    def test_a_provider_is_logged_in_then_its_model_added_at_its_own_mode(self):
        screen = Screen(self, child=CHILD, text=ONE)
        lines = through(screen)
        # installed, since its program was nowhere; the logged-in provider first
        self.assertEqual(verbs(screen), ["opencode install ", "opencode providers "])
        self.assertEqual(listed(lines), [["Acme Plan", "acme", "logged in"],
                                         ["Zeta Cloud", "zeta"], ["MiMo", "mimo"]])
        mark = len(screen.text())
        lines = screen.press(DOWN + ENTER, lambda lines: "  model" in lines and listed(lines))
        # logged in on the terminal given back for it, then asked again for its mode
        self.assertEqual(verbs(screen)[2:], ["opencode login zeta", "opencode providers "])
        said = screen.text()[mark:]
        login = said.index("<opencode login on the terminal>")
        self.assertLess(said.index(GIVE), login)
        self.assertLess(login, said.index(TAKE, login))
        self.assertIn("  provider  Zeta Cloud · zeta", lines)
        self.assertEqual(listed(lines), [["Comet 2", "zeta/comet-2"]])   # its own models only
        lines = screen.press(ENTER, lambda lines: "  effort" in lines)
        self.assertEqual(listed(lines), [["none"]])
        lines = screen.press(ENTER, lambda lines: title(lines) == MATRIX)
        # by the name OpenCode gives it, on its row and over its models
        self.assertEqual(providers(lines), ["Providers      Claude  Zeta Cloud  + add  − remove"])
        self.assertIn("Zeta Cloud", [line.strip() for line in lines])
        saved = screen.saved()
        # priced by OpenCode: pay as you go, used only once every subscription runs ahead
        self.assertEqual(saved["providers"]["zeta"], {"mode": "payg", "name": "Zeta Cloud"})
        self.assertEqual(saved["models"]["comet"], {"harness": "opencode", "model": "zeta/comet-2",
                                                    "effort": "none", "provider": "zeta"})
        self.assertEqual(saved["defaults"], {"orchestrator": "opus", "workers": ["opus"]})
        screen.leave()

    def test_a_logged_in_provider_needs_no_login_and_a_shipped_one_keeps_its_table(self):
        screen = Screen(self, child=CHILD, text=ONE)
        through(screen)
        screen.press(ENTER, lambda lines: "  model" in lines and listed(lines))
        screen.press(ENTER, lambda lines: "  effort" in lines)
        screen.press(DOWN + ENTER, lambda lines: title(lines) == MATRIX)
        self.assertNotIn("opencode login acme", verbs(screen))
        saved = screen.saved()
        self.assertEqual(saved["providers"]["acme"], {"mode": "subscription", "name": "Acme Plan"})
        self.assertEqual(saved["models"]["rocket"]["effort"], "max")
        # MiMo is shipped: its table as it ships, whose mode its endpoint says
        lines = through(screen)
        self.assertEqual(listed(lines)[0], ["Acme Plan", "acme", "logged in"])
        screen.press(DOWN * 2 + ENTER, lambda lines: "  model" in lines and listed(lines))
        screen.press(ENTER, lambda lines: "  effort" in lines)
        screen.press(ENTER, lambda lines: title(lines) == MATRIX)
        self.assertEqual(screen.saved()["providers"]["mimo"], SHIPPED["providers"]["mimo"])
        screen.leave()

    def test_esc_on_the_providers_adds_nothing(self):
        screen = Screen(self, child=CHILD, text=ONE)
        before = screen.path.read_bytes()
        through(screen)
        screen.press(ESC, lambda lines: title(lines) == MATRIX)
        self.assertEqual(screen.path.read_bytes(), before)
        screen.leave()


if __name__ == "__main__":
    unittest.main()
