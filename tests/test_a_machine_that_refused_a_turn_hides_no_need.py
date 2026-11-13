"""A machine lasting long enough that refuses a turn at `prepare` has no room after all: the turn
placed on one Google ends within a rent and a pass of its hour still asks the tick for another.
In-process: a clock, machines and ssh of the test's own.
"""

from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config, google_cloud, helper

CPUS = {"acme-full": 2, "acme-soon": 8}
NOW = 2_000_000_000


class AMachineThatRefusedATurnHidesNoNeed(unittest.TestCase):
    def test_only_requests_for_work_still_marked_reach_the_tick(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, "HOME", Path(tmp)), \
                patch.object(config, "STATE", Path(tmp)), \
                patch.object(google_cloud, "renting", return_value=True):
            path, noted = Path(tmp) / config.CONFIG_NAME, Path(tmp) / google_cloud.NEED
            path.write_text('[google_cloud]\nwork = ["tests"]\n')
            google_cloud.need(1000, "turns")
            self.assertFalse(noted.exists())
            google_cloud.need(2000, "tests")
            path.write_text('[google_cloud]\nwork = ["turns"]\n')
            self.assertEqual(google_cloud._noted(noted), 0)
            google_cloud.need(3000, "turns")
            self.assertEqual(google_cloud._noted(noted), 3000)
            noted.write_text("4000\n")     # a request from before kinds were recorded
            self.assertEqual(google_cloud._noted(noted), 0)

    def test_the_turn_on_the_one_ending_soon_asks_for_another(self):
        def remote(alias, verb, *_args, **kw):
            if not kw:    # the argv of a piece, measured
                return ["ssh", alias, verb]
            said = f"cpus {CPUS[alias]}\nload 0\nroom_mb 65536\nturns 1\n"
            refused = verb == "prepare" and alias == "acme-full"
            return SimpleNamespace(returncode=helper.FULL if refused else 0,
                                   stdout=said if verb == "probe" else "")

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(config, "STATE", Path(tmp)), \
                patch.object(helper.machines, "helpers", return_value=[*CPUS]), \
                patch.object(helper.machines, "work", return_value=["turns", "tests"]), \
                patch.object(google_cloud, "renting", return_value=True), \
                patch.object(google_cloud, "serving", return_value={
                    "acme-full": NOW + 21600, "acme-soon": NOW + 4200}), \
                patch.object(helper, "time", SimpleNamespace(time=lambda: NOW)), \
                patch.object(helper, "_remote", side_effect=remote), \
                patch.object(helper, "_recipe", return_value=("ak-helper-acme:1", {})), \
                patch.object(helper, "_parcel"), \
                patch.object(helper.orch, "agent_programs", return_value={}):
            subprocess.run(["git", "init", "-q", tmp], check=True)
            away = helper.start(2, 2048, tmp, lambda line: None, "true", lambda tar: None,
                                lasting=3600)[0]
            self.assertEqual(away.alias, "acme-soon")
            self.assertTrue((Path(tmp) / google_cloud.NEED).exists())


if __name__ == "__main__":
    unittest.main()
