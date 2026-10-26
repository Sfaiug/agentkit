"""Removing a company's last model leaves its provider in the config, and its usage read from
the cache and its credits unspent: config.remove_model and usage.collect, in a child process
with a temporary HOME.  Nothing here reads or writes the owner's ~/.agentkit.
"""

import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest

from test_config_matrix import INHERITED, REPO

# Google's and OpenAI's only models removed and saved, then a fresh usage cache read back with
# a reset check due: Google's reading has no reset count, OpenAI's a spent week and two credits.
# The adapters are stubbed; what they were asked is printed.
USAGE = r"""
import json, os, sys, time, tomllib
sys.path.insert(0, os.environ["MATRIX_REPO"])
from agentkit import config, usage

cfg = tomllib.loads((config.REPO / "config.default.toml").read_text())
cfg["models"]["spark2"] = dict(cfg["models"]["spark"], model="muse-spark-1.3")
config.remove_model(cfg, "spark")
config.remove_model(cfg, "gemini")
config.save(config.remove_model(cfg, "astra"))
asked = []
usage._adapter_json = lambda harness, verb, *_: asked.append(f"{harness} {verb}") or {}
now = time.time()
week = {"window_secs": 7 * 86400, "used": 95, "resets_at": now + 86400}
(config.STATE / "usage.json").write_text(json.dumps({
    "fetched_at": now, "reset_checked_at": 0, "providers": {
        "google": {"provider": "google", "meters": [], "error": "unknown", "resets": None,
                   "probed_at": now},
        "openai": {"provider": "openai", "harness": "codex", "meters": [week], "resets": 2,
                   "probed_at": now}}}))
read = usage.collect(config.load())
print(json.dumps({"saved": tomllib.loads(config.dump(config.load())),
                  "google": read["google"]["error"], "asked": asked}))
"""


class LastModelLeavesProvider(unittest.TestCase):
    def test_a_company_s_last_model_leaves_its_provider_its_usage_read_and_its_credits(self):
        home = tempfile.TemporaryDirectory(prefix="last-model-")
        self.addCleanup(home.cleanup)
        env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        env.update({"HOME": home.name, "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
                    "MATRIX_REPO": str(REPO)})
        done = subprocess.run([sys.executable, "-c", USAGE], env=env, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        answer = json.loads(done.stdout)
        shipped = tomllib.loads((REPO / "config.default.toml").read_text())
        saved = answer["saved"]
        self.assertNotIn("gemini", saved["models"])
        self.assertNotIn("astra", saved["models"])
        self.assertEqual(saved["providers"]["google"], shipped["providers"]["google"])
        self.assertEqual(saved["providers"]["openai"], shipped["providers"]["openai"])
        self.assertNotIn("usage_model", saved["providers"]["meta"])     # it named spark
        self.assertEqual(saved["providers"]["meta"]["usage_effort"], "minimal")
        self.assertEqual(saved["defaults"], {"orchestrator": "opus", "workers": ["opus"]})
        self.assertEqual(answer["google"], "unknown")     # read from the cache, never raised
        self.assertEqual(answer["asked"], [])             # no credit spent with no model to use it


if __name__ == "__main__":
    unittest.main()
