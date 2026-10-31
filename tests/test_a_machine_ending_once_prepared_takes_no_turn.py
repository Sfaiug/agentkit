"""A turn's machine must last `lasting` seconds from when the turn starts there, once its
`prepare`, which may take 30 minutes, is over: one whose end that brought too near is finished
with, and the turn goes to the next. In-process: a clock, machines and ssh of the test's own.
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

CPUS = {"acme-wide": 8, "acme-narrow": 2}


class AMachineEndingOncePreparedTakesNoTurn(unittest.TestCase):
    def test_the_turn_goes_to_the_next(self):
        now, asked = [2_000_000_000], []

        def remote(alias, verb, *_args, **kw):
            if not kw:    # the argv of a piece, measured
                return ["ssh", alias, verb]
            asked.append((verb, alias))
            if verb == "prepare":
                now[0] += 120    # a first image build
            said = f"cpus {CPUS[alias]}\nload 0\nroom_mb 65536\nturns 1\n"
            return SimpleNamespace(returncode=0, stdout=said if verb == "probe" else "")

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(config, "STATE", Path(tmp)), \
                patch.object(helper.machines, "helpers", return_value=[*CPUS]), \
                patch.object(google_cloud, "serving", return_value={
                    "acme-narrow": now[0] + 3630, "acme-wide": now[0] + 21600}), \
                patch.object(helper, "time", SimpleNamespace(time=lambda: now[0])), \
                patch.object(helper, "_remote", side_effect=remote), \
                patch.object(helper, "_recipe", return_value=("ak-helper-acme:1", {})), \
                patch.object(helper, "_parcel"), \
                patch.object(helper.orch, "agent_programs", return_value=[]):
            subprocess.run(["git", "init", "-q", tmp], check=True)
            away = helper.start(2, 2048, tmp, lambda line: None, "true", lambda tar: None,
                                lasting=3600)[0]
        self.assertEqual(away.alias, "acme-wide")
        self.assertEqual([one for one in asked if one[0] in ("prepare", "finish")], [
            ("prepare", "acme-narrow"), ("finish", "acme-narrow"), ("prepare", "acme-wide")])


if __name__ == "__main__":
    unittest.main()
