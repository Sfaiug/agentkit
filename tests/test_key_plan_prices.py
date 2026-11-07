"""Each login's `a month` on `ak usage` is its own price: the `price` on its provider's table
where the config sets one, else the list price of the plan state/logins.json says the login is on
now, else none, `-`.  Claude's Pro is $20 a month, Max 20x $200 and Max 5x $100, ChatGPT's Pro
$200 and Google AI Pro $19.99.  `ak usage --json` gives each login its `price`.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each of
the `claude`, `codex` and `antigravity` harnesses being tests/fixtures/meters.py's script beside
its shipped manifest, with invented logins written into its Home, on a terminal wide enough for
the whole table.  Fails against /bin/false.
"""

import json
from pathlib import Path
import shutil
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home

WIDE = {"COLUMNS": "200"}
# (provider, account): (its row on `ak usage`, the plan its login is on)
PLANS = {("anthropic", "default"): ("anthropic I", "max 20x"),
         ("anthropic", "second"): ("anthropic II", "pro"),
         ("openai", "default"): ("openai", "pro"),
         ("google", "default"): ("google", "Google AI Pro")}


class PlanPrices(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        meter = meters.install(self.home)
        for harness in ("claude", "codex", "antigravity"):
            shutil.copy2(meter.dir / "echo.sh", meter.dir / f"{harness}.sh")
        for provider, account in PLANS:
            meter.week(provider, account, used=50)
        self.plans = {login: plan for login, (_, plan) in PLANS.items()}

    def usage(self, **providers):
        """Each login's (`price` on `ak usage --json`, `a month` on `ak usage`), its provider's
        table given its keys in `providers`, each login on its plan in `self.plans`."""
        akconfig.write(self.home, {"anvil": "claude", "bolt": "codex", "crux": "antigravity"},
                       providers={"anthropic": {"mode": "subscription",
                                                "accounts": ["default", "second"],
                                                **providers.get("anthropic", {})},
                                  **{name: {"mode": "subscription", **providers.get(name, {})}
                                     for name in ("openai", "google")}})
        logins = {}
        for (provider, account), plan in self.plans.items():
            logins.setdefault(provider, {})[account] = {
                "email": f"{account}@{provider}.test", "ends": None, "plan": plan,
                "checked_at": time.time()}
        self.home.write(".agentkit/state/logins.json", logins)
        data = self.home.ak("usage", "--json")
        self.assertEqual(data.code, 0, data.out + data.err)
        text = self.home.ak("usage", env=WIDE)
        self.assertEqual(text.code, 0, text.out + text.err)
        found = json.loads(data.out)["providers"]
        records = {(name, account): (found[name]["accounts"][account] if name == "anthropic"
                                     else found[name]) for name, account in PLANS}
        return {login: (records[login]["price"], meters.cell(text.out, label, "a month"))
                for login, (label, _) in PLANS.items()}

    def test_each_login_is_priced_at_its_own_plan(self):
        self.assertEqual(self.usage(), {("anthropic", "default"): (200, "200"),
                                        ("anthropic", "second"): (20, "20"),
                                        ("openai", "default"): (200, "200"),
                                        ("google", "default"): (19.99, "19.99")})

    def test_a_price_on_the_providers_table_wins_over_its_plan(self):
        got = self.usage(anthropic={"price": 150})
        self.assertEqual(got[("anthropic", "default")], (150, "150"))
        self.assertEqual(got[("anthropic", "second")], (150, "150"))
        self.assertEqual(got[("openai", "default")], (200, "200"))

    def test_a_plan_not_listed_or_no_plan_has_no_price(self):
        self.plans[("anthropic", "second")] = "team"
        self.plans[("openai", "default")] = None
        del self.plans[("google", "default")]
        got = self.usage()
        for login in (("anthropic", "second"), ("openai", "default"), ("google", "default")):
            self.assertEqual(got[login], (None, "-"), login)
        self.assertEqual(got[("anthropic", "default")], (200, "200"))

    def test_a_login_whose_plan_changes_has_the_new_plans_price(self):
        self.assertEqual(self.usage()[("anthropic", "default")], (200, "200"))
        self.plans[("anthropic", "default")] = "max 5x"
        self.plans[("google", "default")] = "Google AI Ultra"
        got = self.usage()
        self.assertEqual(got[("anthropic", "default")], (100, "100"))
        self.assertEqual(got[("google", "default")], (249.99, "249.99"))


if __name__ == "__main__":
    unittest.main()
