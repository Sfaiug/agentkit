"""A piece a machine lost answers from the machine that runs it next as any piece does: red
there, it runs again here on a turn; run here on a turn the wait took, it knows it holds one
(`AK_HEAVY_TURN`). Offline: test_suite_helper's fake `ssh` answers both machines' probes; the
pieces' exits and this host's turns are faked.
"""

import io
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_suite_helper as fixture
from test_suite_on_both import Turn
from agentkit import gate, helper, worker


class LostPiecesAnswerAsAnyOther(unittest.TestCase):
    def setUp(self):
        fixture.SuiteHelper.setUp(self)

    def turn(self, *_args, wait=True, elsewhere=None, **_kw):
        # no turn is free as the suite starts; waiting, the next machine answers first
        if wait and (not elsewhere or not elsewhere() or self.with_turn):
            return Turn(1)

    def suite(self, code, with_turn):
        """(place, piece, AK_HEAVY_TURN) of each go: machine 0 loses every piece it runs,
        machine 1 exits `code`; a turn here comes after it answers, or, `with_turn`, with it."""
        self.with_turn, ran, keys, here_ran = with_turn, [], {}, threading.Event()

        def there(argv, *_args, env, **_kw):
            machine = keys.setdefault(argv[0].key, len(keys))
            if machine and with_turn:
                here_ran.wait(10)
            ran.append((machine, env["AK_SHARD"], None))
            return (code if machine else helper.LOST), "", False

        def here(_argv, *_args, env, **_kw):
            ran.append(("here", env["AK_SHARD"], env.get("AK_HEAVY_TURN")))
            here_ran.set()
            return 0, "", False

        with patch.object(helper, "piece", lambda away, *_args: [away]), \
                patch.object(worker, "limited", side_effect=there), \
                patch.object(worker, "boxed", side_effect=here):
            result = gate.run_suite(fixture.SUITE, 30, cwd=self.repo,
                                    activity=self.root / "live.log", output=io.BytesIO())
        self.assertEqual(result[0], 0, result[1])
        return ran

    def test_a_piece_red_on_the_next_machine_runs_again_here_on_a_turn(self):
        ran = self.suite(1, with_turn=False)
        self.assertEqual(sorted(go[1:] for go in ran if go[0] == "here"),
                         sorted((shard, "1") for machine, shard, _ in ran if machine == 1))

    def test_a_piece_run_on_a_turn_the_wait_took_holds_it(self):
        ran = self.suite(0, with_turn=True)
        self.assertEqual({heavy for place, _, heavy in ran if place == "here"}, {"1"})


if __name__ == "__main__":
    unittest.main()
