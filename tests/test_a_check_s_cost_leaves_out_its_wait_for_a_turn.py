"""A red whole check keeps the parts it confirmed only where what the timing record holds for
their tests, together, is less than the check took, its wait for a turn left out: once the turn
is free, that wait makes the parts run alone no quicker than the top checked whole.

Offline: a temporary HOME, an injected clock, turn and runner.
"""

from contextlib import ExitStack, contextmanager
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config, gate, gitcall, land, run, suite_times

SUITE = ': "$AK_SHARD"; acme-suite'


class ACheckSCostLeavesOutItsWaitForATurn(unittest.TestCase):
    def parts(self, wait, record):
        """The parts a 10-second check confirming `t/a.sh` and `t/b.sh` red, in two pieces,
        keeps after `wait` seconds for its turn, the record holding `record`."""
        now = [0.0]

        @contextmanager
        def turn(*_args, **_kw):
            now[0] += wait
            yield

        def check(*_args, marks, pieces, confirmed, **_kw):
            now[0] += 10
            marks.append(1)
            pieces[SUITE] = {"1/2": 1, "2/2": 1}
            confirmed[SUITE] = {"1/2": ["t/a.sh"], "2/2": ["t/b.sh"]}
            return False, "FAIL  t/a.sh"

        with ExitStack() as stack:
            root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            for target, name, value in (
                    (config, "HOME", root / ".agentkit"),
                    (land, "time", SimpleNamespace(monotonic=lambda: now[0])),
                    (gitcall, "commit_identity", lambda _: {"head_sha": "c0", "tree_sha": "t0"}),
                    (run, "git_out", lambda *_args, **_kw: (0, "")),
                    (land, "_flaked", lambda *_args: None),
                    (gate, "gate_turn", turn), (gate, "run_done_when", check),
                    (suite_times, "handed", lambda _: record)):
                stack.enter_context(patch.object(target, name, value))
            state = {"repo": str(root), "waiting_on": {"joined": 1, "line": ".merge-acme"}}
            answer = land._check_tree(root, state, root, "t0", [SUITE], lambda _: None, SUITE)
        return [part["tests"] for part in answer["parts"]]

    def test_parts_slower_than_the_check_are_dropped_however_long_its_turn_took(self):
        for wait in (0, 100):
            self.assertEqual(self.parts(wait, '{"t/a.sh": 40, "t/b.sh": 40}'), [], wait)

    def test_parts_quicker_than_the_check_are_kept(self):
        self.assertEqual(self.parts(0, '{"t/a.sh": 4, "t/b.sh": 4}'), [["t/a.sh"], ["t/b.sh"]])


if __name__ == "__main__":
    unittest.main()
