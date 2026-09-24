"""One list of models, each an orchestrator and a worker, and the defaults a seat takes. Offline.

A throwaway HOME holds every config and cache here, so the owner's ~/.agentkit is never read
or written; meters are hand-written dicts and no adapter is asked anything.  What is pinned is
the shipped `[defaults]`, the way a config from before it still reads, the orchestrator choice
falling through a spent default in list order, the default workers answering wherever no
session does, and a provider taken out whole -- its models, its places in the defaults, its
usage row and its probe -- except the last one, which cannot go.
"""

from contextlib import ExitStack, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, run, terminal, usage

DEFAULT = REPO / "config.default.toml"

OLD = """max_runs = 3

[tiers]
A = ["fable", "opus"]
B = ["opus", "astra", "fable"]
pace_margin = 7

[models.fable]
harness = "claude"
model = "claude-fable-5-1"
effort = "xhigh"
provider = "anthropic"
meter = "weekly_scoped"

[models.opus]
harness = "claude"
model = "claude-opus-5-5"
effort = "xhigh"
provider = "anthropic"

[models.astra]
harness = "codex"
model = "default"
effort = "xhigh"
provider = "openai"

[providers.anthropic]
mode = "subscription"

[providers.openai]
mode = "subscription"
"""


class Defaults(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".defaults-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "NO_COLOR": "1"}))
        self.home = self.root / ".agentkit"
        self.stack.enter_context(patch.object(config, "HOME", self.home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.home / name.lower()))
        self.path = self.home / config.CONFIG_NAME
        config.ensure_dirs()
        self.now = time.time()

    def meter(self, name, used):
        return {"name": name, "used": float(used), "pace": 0.0, "elapsed": 50.0,
                "window_secs": 604800, "resets_at": self.now + 302400}

    def providers(self, cfg, anthropic=10, openai=10):
        """One weekly reading per provider, the flags set the way a real read sets them."""
        providers = {name: {"meters": [self.meter("weekly", 10)], "resets": 0}
                     for name in cfg["providers"]}
        providers["anthropic"]["meters"] = [self.meter("weekly_all", anthropic),
                                            self.meter("weekly_scoped", anthropic)]
        providers["openai"]["meters"] = [self.meter("weekly", openai)]
        return usage._gate_flags(providers, self.now, cfg)

    def test_the_shipped_defaults_offer_every_model_both_ways(self):
        cfg = config.load()
        self.assertEqual(cfg["defaults"], {"orchestrator": "opus", "workers": ["opus", "astra"]})
        shipped = tomllib.loads(DEFAULT.read_text())
        self.assertNotIn("tiers", shipped)
        self.assertEqual(config.offered(cfg), list(shipped["models"]))
        self.assertEqual(usage.margin(cfg), 10.0)
        # any model orchestrates and any model works, the default orchestrator for itself too
        for name in config.offered(cfg):
            model, reason, workers = orch.select(cfg, {}, forced=name, forced_workers=name,
                                                 prompting=False)
            self.assertEqual((model, reason, workers), (name, "--model", [name]))
        # a model whose provider has no table is in the file and in no choice
        cfg["models"]["stray"] = {**cfg["models"]["opus"], "provider": "gone"}
        self.assertNotIn("stray", config.offered(cfg))

    def test_an_old_tiers_config_reads_as_its_first_orchestrator_for_the_rest(self):
        self.path.write_text(OLD)
        cfg = config.load()
        self.assertEqual(cfg["defaults"], {"orchestrator": "fable", "workers": ["opus", "astra"]})
        self.assertNotIn("tiers", cfg)
        self.assertEqual(usage.margin(cfg), 7.0)
        self.assertEqual(config.workers(cfg), ["opus", "astra"])
        # reading it rewrites nothing; the owner's next save writes the new shape
        self.assertEqual(self.path.read_text(), OLD)
        config.save(cfg)
        saved = tomllib.loads(self.path.read_text())
        self.assertNotIn("tiers", saved)
        self.assertEqual(saved["defaults"], cfg["defaults"])
        self.assertEqual((saved["pace_margin"], saved["max_runs"]), (7, 3))
        self.assertEqual(config.load()["defaults"], cfg["defaults"])
        # a first orchestrator that is also its only worker still leaves a seat someone to work
        self.path.write_text(OLD.replace('B = ["opus", "astra", "fable"]', 'B = ["fable"]'))
        self.assertEqual(config.load()["defaults"], {"orchestrator": "fable", "workers": ["fable"]})

    def test_a_spent_default_orchestrator_falls_through_in_list_order(self):
        cfg = config.load()
        fine = self.providers(cfg)
        self.assertEqual(orch.choose(cfg, fine)[0], "opus")
        # opus is spent, and so is fable on the same provider: the next in file order is astra
        spent = self.providers(cfg, anthropic=100)
        model, reason = orch.choose(cfg, spent)
        self.assertEqual(model, "astra")
        self.assertIn("skipped opus: weekly_all 100.0% used", reason)
        self.assertIn("skipped fable:", reason)
        # `n` offers it with Enter, the skips beside it, and the default workers after it
        out = io.StringIO()
        with patch.object(terminal, "readline",
                          side_effect=lambda prompt="": print(prompt, end="") or ""), \
                redirect_stdout(out):
            self.assertEqual(orch.select(cfg, spent, prompting=True),
                             ("astra", reason, ["opus", "astra"]))
        self.assertIn("Orchestrator [astra] (skipped opus:", out.getvalue())
        self.assertIn("Workers [opus astra]:", out.getvalue())
        # with every model spent the default still takes the seat, with a WARN
        everything = self.providers(cfg, anthropic=100, openai=100)
        for prov in everything.values():
            prov["meters"] = [self.meter(m["name"], 100) for m in prov["meters"]]
        usage._gate_flags(everything, self.now, cfg)
        model, reason = orch.choose(cfg, everything)
        self.assertEqual(model, "opus")
        self.assertTrue(reason.startswith("WARN"), reason)
        self.assertIn("launching opus anyway", reason)

    def test_workers_outside_a_session_are_the_default_workers(self):
        cfg = config.load()
        self.assertIsNone(config.active_session(cfg))
        self.assertEqual(config.workers(cfg), ["opus", "astra"])
        self.assertEqual(orch.select(cfg, {}, prompting=False)[2], ["opus", "astra"])
        self.assertEqual(sorted(usage.pick_order(cfg, self.providers(cfg), quiet=True)),
                         ["astra", "opus"])
        self.assertEqual(run.job_next_executor(cfg, "opus"), "astra")
        cfg["defaults"]["workers"] = ["grok"]
        self.assertEqual(config.workers(cfg), ["grok"])
        # a session answers for itself, whatever the defaults say
        config.save_session(cfg, "seat", "mimo", ["spark", "fable"])
        with patch.dict(os.environ, {config.SESSION_ENV: "seat"}):
            self.assertEqual(config.workers(cfg), ["spark", "fable"])

    def test_removing_a_provider_takes_its_models_defaults_and_usage_row(self):
        cfg = config.load()
        self.assertIs(config.remove_provider(cfg, "anthropic"), cfg)
        self.assertNotIn("anthropic", cfg["providers"])
        self.assertNotIn("fable", cfg["models"])
        self.assertNotIn("opus", cfg["models"])
        # the orchestrator went with it, so the first model left takes its place; astra stays
        self.assertEqual(cfg["defaults"], {"orchestrator": "astra", "workers": ["astra"]})
        config.save(cfg)
        cfg = config.load()
        self.assertEqual(cfg["defaults"], {"orchestrator": "astra", "workers": ["astra"]})
        # a fresh cache still holding the provider shows it nowhere and reads it again nowhere
        readings = {name: {"provider": name, "meters": [self.meter("weekly", 30)], "resets": 0}
                    for name in ("anthropic", "openai", "meta", "xai", "mimo", "google")}
        cache = config.STATE / "usage.json"
        cache.write_text(json.dumps({"fetched_at": self.now, "reset_checked_at": self.now,
                                     "providers": readings}))
        probed = []

        def probe(cfg, provider):
            probed.append(provider)
            return copy.deepcopy(readings[provider])
        with patch.object(usage, "_probe_gently", side_effect=probe):
            self.assertNotIn("anthropic", usage.collect(cfg))
            self.assertEqual(probed, [])
            self.assertNotIn("anthropic", usage.collect(cfg, refresh=True))
        self.assertEqual(probed, ["openai", "meta", "xai", "google", "mimo"])
        cache.write_text(json.dumps({"fetched_at": self.now, "reset_checked_at": self.now,
                                     "providers": readings}))
        rows = "\n".join(menu.usage_lines(cfg, 80))
        self.assertIn("ChatGPT", rows)
        self.assertNotIn("Claude", rows)
        self.assertNotIn("anthropic", [row[0] for row in usage.rows(cfg, usage.collect(cfg))])
        env = {**os.environ, "HOME": str(self.root), "AGENTKIT_SESSION": "",
               "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, str(REPO / "bin/ak"), "usage", "--json"],
                                env=env, capture_output=True, text=True, cwd=self.root,
                                timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(sorted(data["providers"]), ["google", "meta", "mimo", "openai", "xai"])
        self.assertNotIn("opus", data["pick_order"])

    def test_the_last_provider_cannot_be_removed(self):
        cfg = config.load()
        for name in ("openai", "meta", "xai", "mimo", "google"):
            config.remove_provider(cfg, name)
        self.assertEqual(list(cfg["providers"]), ["anthropic"])
        self.assertEqual(cfg["defaults"], {"orchestrator": "opus", "workers": ["opus"]})
        kept = copy.deepcopy(cfg)
        with self.assertRaisesRegex(config.Error, "last provider"):
            config.remove_provider(cfg, "anthropic")
        self.assertEqual(cfg, kept)
        with self.assertRaisesRegex(config.Error, "no provider 'nobody'"):
            config.remove_provider(cfg, "nobody")
        self.assertEqual(cfg, kept)


if __name__ == "__main__":
    unittest.main()
