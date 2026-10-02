"""Check 4 runs on whichever configured models have budget now, the pair ak's own pick gives.

tests/check4_pair.py is called in-process on fake usage files, each harness ready unless a test
says it is missing: no suite runs, no harness is asked and no model is called.
"""

from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import check4_pair
from agentkit import config, usage

SMOKE = (REPO / "tests/smoke.sh").read_text()
CHECK4 = SMOKE[SMOKE.index("# --- 4: ak run end to end"):SMOKE.index("# --- 5: notify")]
CFG = {"defaults": {"orchestrator": "opus", "workers": ["opus", "astra"]},
       "models": {"opus": {"harness": "test", "model": "opus-1", "effort": "high",
                           "provider": "anthropic"},
                  "astra": {"harness": "test", "model": "astra-1", "effort": "high",
                            "provider": "openai"}},
       "providers": {"anthropic": {}, "openai": {}}}


def reading(used):
    """A provider's record with one weekly meter at `used`% halfway through its week."""
    return {"meters": [{"name": "weekly", "used": used, "pace": used - 50, "elapsed": 50,
                        "window_secs": 604800, "resets_at": time.time() + 302400}], "resets": 0}


class Check4PicksModelsWithBudget(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="check4-pair-")
        self.addCleanup(tmp.cleanup)
        self.suite, self.host = Path(tmp.name) / "suite.json", Path(tmp.name) / "host.json"
        self.cfg, self.missing = copy.deepcopy(CFG), {}
        for target, name, value in ((config, "load", lambda: copy.deepcopy(self.cfg)),
                                    (config, "active_session", lambda cfg: None),
                                    (usage, "harness_unready",
                                     lambda harness, **_kw: self.missing.get(harness))):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def pair(self, suite, host=None):
        """What the helper prints for this suite snapshot and host cache."""
        self.suite.write_text(json.dumps({"providers": suite}))
        self.host.write_text(json.dumps({"providers": host or {}}))
        self.out = io.StringIO()
        with redirect_stdout(self.out):
            check4_pair.main(str(self.suite), str(self.host))
        return self.out.getvalue()

    def test_one_open_model_executes_and_reviews(self):
        self.assertEqual(self.pair({"anthropic": reading(10), "openai": reading(100)}),
                         "opus opus\n")

    def test_the_reviewer_comes_from_the_other_provider(self):
        self.assertEqual(self.pair({"anthropic": reading(10), "openai": reading(70)}),
                         "opus astra\n")
        # the executor is whoever has the most budget now
        self.assertEqual(self.pair({"anthropic": reading(70), "openai": reading(10)}),
                         "astra opus\n")

    def test_everything_spent_prints_nothing(self):
        self.assertEqual(self.pair({"anthropic": reading(100), "openai": reading(100)}), "")

    def test_a_model_outside_the_default_workers_runs_it(self):
        self.cfg["models"]["spark"] = {"harness": "spark-cli", "model": "spark-1",
                                       "effort": "high", "provider": "meta"}
        self.cfg["providers"]["meta"] = {}
        self.assertEqual(self.pair({"anthropic": reading(100), "openai": reading(100),
                                    "meta": reading(10)}), "spark spark\n")

    def test_open_models_this_host_cannot_run_say_why(self):
        self.missing["test"] = "test is not installed"
        with self.assertRaises(SystemExit) as exited:
            self.pair({"anthropic": reading(10), "openai": reading(100)})
        self.assertEqual(exited.exception.code, 3)
        self.assertEqual(self.out.getvalue(), "test is not installed\n")
        # spent first: a host that lacks only spent models has nothing it could run anyway
        self.assertEqual(self.pair({"anthropic": reading(100), "openai": reading(100)}), "")

    def test_a_provider_the_suite_read_knows_nothing_of_reads_as_the_host_cache(self):
        # the host asked inside the shared cadence, so the suite's read is empty
        unknown = {"meters": [], "error": "unknown: asked inside the cadence"}
        self.assertEqual(self.pair({"anthropic": reading(10), "openai": unknown},
                                   {"openai": reading(100)}), "opus opus\n")
        # a refusal check 3 recorded stands over the host's older room
        refused = {"meters": [], "exhausted_until": time.time() + 3600}
        self.assertEqual(self.pair({"anthropic": reading(10), "openai": refused},
                                   {"openai": reading(10)}), "opus opus\n")

    def test_check_4_names_no_model_and_picks_before_it_takes_a_target(self):
        names = tomllib.loads((REPO / "config.default.toml").read_text())["models"]
        source = CHECK4 + (REPO / "tests/check4_pair.py").read_text()
        self.assertEqual([n for n in names if re.search(rf"\b{re.escape(n)}\b", source)], [])
        self.assertLess(CHECK4.index("check4_pair.py"), CHECK4.index("smoke_lock_hold"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
