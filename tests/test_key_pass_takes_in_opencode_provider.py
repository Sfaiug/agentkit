"""A model picked inside an OpenCode seat, of another provider than the entry the seat leaves, is
added by the watch's pass as `+ add a subscription` takes one in: that provider's table where
the config has none, and the mode OpenCode lists for its login on the entry where the table says
another -- a table that came with Codex's plan pays for no call OpenCode makes on an OpenAI key.
The pass asks OpenCode's providers once however many seats need them, and a look none; a
provider it lists with no mode adds nothing.

Black-box against AK_BIN, running a pass as test_key_model_added_from_its_harness_s_listing does:
a fake OpenCode adapter answers `models` and `providers` and logs each ask, and each seat's
answers are written where OpenCode keeps them (test_key_opencode_model_added_under_its_provider).
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from test_key_opencode_model_added_under_its_provider import bar, record, seats

NOVA = "acme/nova-7"              # Acme's, logged in on OpenCode alone: the config has no table
VEGA = "openai/vega-6"           # OpenAI's, on a key: the config's table is Codex's plan
ZETA = "zeta/zeta-2"              # Zeta's, listed with no login
MODELS = "\n".join(f"{model}\t{label}\tlow high" for model, label in (
    (NOVA, "Nova 7"), (VEGA, "Vega 6"), (ZETA, "Zeta 2")))
PROVIDERS = "acme\tAcme\tpayg\t\nopenai\tOpenAI\tpayg\t\nzeta\tZeta\t\tkey"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class PassTakesInOpencodeProvider(unittest.TestCase):
    def test_a_pass_adds_a_model_of_another_provider_as_opencode_lists_its_login(self):
        home = Home()
        self.addCleanup(home.close)
        opencode = fakeadapter.install(home, opencode="pass", codex="pass")["opencode"]
        opencode.answer("models", MODELS)
        opencode.answer("providers", PROVIDERS)
        akconfig.write(home, {"mimo": {}, "astra": {}})
        seats(home, {"acme-nova": ("mimo", NOVA), "acme-vega": ("mimo", VEGA),
                     "acme-zeta": ("mimo", ZETA)})
        before = akconfig.read(home)

        for name in ("acme-nova", "acme-vega", "acme-zeta"):
            self.assertEqual(home.ak("orch", "why", name).code, 0)
            self.assertEqual(record(home, name)["orchestrator"], "mimo")
            self.assertIn("MiMo V2.6 Pro", bar(home, name))
        after = akconfig.read(home)
        self.assertEqual((after["models"], after["providers"]),
                         (before["models"], before["providers"]))
        self.assertEqual(opencode.calls("providers"), [])           # a look asks none

        done = home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(len(opencode.calls("providers")), 1)       # once, for every seat
        after = akconfig.read(home)
        added = {entry["model"]: name for name, entry in after["models"].items()
                 if name not in before["models"]}
        self.assertEqual(sorted(added), [NOVA, VEGA])
        self.assertEqual(after["models"][added[NOVA]], {
            "harness": "opencode", "model": NOVA, "effort": "high", "provider": "acme"})
        self.assertEqual(after["providers"]["acme"], {"mode": "payg", "name": "Acme"})
        self.assertEqual(after["models"][added[VEGA]], {
            "harness": "opencode", "model": VEGA, "effort": "high", "provider": "openai",
            "mode": "payg"})
        self.assertEqual(after["providers"]["openai"], before["providers"]["openai"])
        self.assertEqual(record(home, "acme-nova")["orchestrator"], added[NOVA])
        self.assertIn("Nova 7 high", bar(home, "acme-nova"))
        self.assertEqual(record(home, "acme-vega")["orchestrator"], added[VEGA])
        self.assertIn("Vega 6 high", bar(home, "acme-vega"))

        self.assertEqual(record(home, "acme-zeta")["orchestrator"], "mimo")
        self.assertIn("MiMo V2.6 Pro", bar(home, "acme-zeta"))
        self.assertNotIn("zeta", after["providers"])


if __name__ == "__main__":
    unittest.main()
