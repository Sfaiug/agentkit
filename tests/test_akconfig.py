"""The answer key's config.toml names the models a test gives and nothing else.

A run test that means opus and astra must not get a third model from the shipped config, and
one that turns the audit on or adds a provider must find the file says so; both hold only if
tests/fixtures/akconfig.py does.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home


class Config(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def test_shipped_models_keep_their_entries_and_the_audit_is_off(self):
        akconfig.write(self.home, ["opus", "astra"])
        config = akconfig.read(self.home)
        self.assertEqual(config["defaults"], {"orchestrator": "opus",
                                              "workers": ["opus", "astra"]})
        self.assertEqual(config["models"], {"opus": akconfig.SHIPPED["opus"],
                                            "astra": akconfig.SHIPPED["astra"]})
        self.assertEqual(config["providers"], {"anthropic": {"mode": "subscription"},
                                               "openai": {"mode": "subscription"}})
        self.assertEqual(config["audit"], {"on": False})

    def test_a_new_model_runs_its_own_id_on_the_harness_given(self):
        gamma = {"harness": "claude", "provider": "acme", "effort": "low"}
        akconfig.write(self.home, {"beta": "codex", "gamma": gamma}, workers=["gamma"],
                       orchestrator="gamma", providers={"acme": {"mode": "payg"}},
                       settings={"within": 3}, audit=True, extra='[audit2]\nnote = "kept"')
        config = akconfig.read(self.home)
        self.assertEqual(config["models"], {"beta": {"harness": "codex", "model": "beta",
                                                     "effort": "high", "provider": "openai"},
                                            "gamma": {**gamma, "model": "gamma"}})
        self.assertEqual(config["defaults"], {"orchestrator": "gamma", "workers": ["gamma"]})
        self.assertEqual(config["providers"]["acme"], {"mode": "payg"})
        self.assertEqual((config["within"], config["audit2"]), (3, {"note": "kept"}))
        self.assertNotIn("audit", config)

    def test_ak_meters_exactly_the_providers_of_the_models_written(self):
        akconfig.write(self.home, {"opus": "claude", "beta": "codex"})
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual({provider: row["via"] for provider, row
                          in json.loads(done.out)["providers"].items()},
                         {"anthropic": "opus", "openai": "beta"})


if __name__ == "__main__":
    unittest.main()
