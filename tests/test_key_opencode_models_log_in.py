"""OpenCode's row on `Models` lists every model OpenCode runs, and logs in to the config's
providers it has no login for: one logged in there lists its models, each taken in under it.

On 20 Oct the owner could not pick a GPT model in OpenCode: `Models` listed only the models the
config already ran there, and a model OpenCode could run came in only through `+ add a
subscription`.  Black-box: the program `AK_BIN` names, its menu in a person's terminal
(tests/fixtures/akterm.py), its harnesses the fakes of tests/fixtures/fakeadapter.py, the fake
OpenCode listing `openai` with no login until its `login` runs for `openai`, and its `models`
listing `openai/vega-1` only after that; `zeta`, a provider the config does not hold, is never
logged in.  Judged by what the terminal shows, the fake's calls and config.toml; this test
fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_from_own_login import ticks
from test_key_new_subscription_signs_in_afresh import MAIN_KEYS, lines

# before the fake itself: `login` for openai marks it logged in, which `providers` and `models`
# then say
LOGINS = """d=%s
case "$1" in
  login) [ "$AGENTKIT_PROVIDER" = openai ] && : > "$d/in-openai" ;;
  providers)
    printf 'mimo\\tMiMo\\tpayg\\n'
    if [ -e "$d/in-openai" ]; then printf 'openai\\tOpenAI\\tsubscription\\n'
    else printf 'openai\\tOpenAI\\t\\n'; fi
    printf 'zeta\\tZeta Cloud\\t\\n'; exit 0 ;;
  models)
    printf 'mimo/mimo-v2.6-pro\\tMiMo V2.6 Pro\\tnone high\\n'
    [ -e "$d/in-openai" ] && printf 'openai/vega-1\\tVega 1\\thigh\\n'; exit 0 ;;
esac
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OpenCodeModelsLogIn(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakes = fakeadapter.install(self.home, opencode="pass", codex="pass")
        self.fake = fakes["opencode"]
        self.fake.script.write_text(self.fake.script.read_text().replace(
            "#!/bin/sh\n", "#!/bin/sh\n" + LOGINS % self.fake.dir, 1))
        akconfig.write(self.home, {"mimo": {"harness": "opencode", "model": "mimo/mimo-v2.6-pro",
                                            "effort": "high", "provider": "mimo"}},
                       providers={"mimo": {"mode": "payg"},
                                  "openai": {"mode": "subscription"}})
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen))
        self.term.keys("c")
        self.term.wait("› MiMo V2.6 Pro")

    def to(self, row):
        """The highlight moved, a line at a time, onto the line that starts `row`."""
        for _ in range(20):
            shown = lines(self.term.screen())
            now = next(n for n, line in enumerate(shown) if line.startswith("› "))
            if shown[now].startswith(f"› {row}"):
                return
            there = next(n for n, line in enumerate(shown) if line.startswith(f"  {row}"))
            self.term.keys("Down" if there > now else "Up")
            self.term.wait(lambda screen: lines(screen)[now] != shown[now])
        self.fail(f"the highlight never reached {row}")

    def test_a_provider_logged_in_on_models_lists_its_models_to_take_in(self):
        self.to("Models")
        self.term.keys("Enter")
        self.term.wait("agentkit · config · models")
        self.to("OpenCode")
        self.term.keys("Enter")
        shown = self.term.wait(lambda screen: "OpenAI log in" in screen)
        self.assertEqual(ticks(shown), ["■ MiMo V2.6 Pro"])
        self.assertNotIn("Zeta", shown)
        self.to("  OpenAI log in")
        self.term.keys("Enter")
        shown = self.term.wait(lambda screen: "□ Vega 1" in ticks(screen))
        self.assertNotIn("log in", shown)
        self.assertEqual([call["env"].get("AGENTKIT_PROVIDER")
                          for call in self.fake.calls("login")], ["openai"])
        self.to("  □ Vega 1")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "■ Vega 1" in ticks(screen))
        taken = [entry for entry in akconfig.read(self.home)["models"].values()
                 if entry["model"] == "openai/vega-1"]
        self.assertEqual([(entry["harness"], entry["provider"]) for entry in taken],
                         [("opencode", "openai")])


if __name__ == "__main__":
    unittest.main()
