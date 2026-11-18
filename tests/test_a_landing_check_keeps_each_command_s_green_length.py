"""A whole landing check green as the lander reads it keeps, on each command's cost, how long
that command took (`gate.green_seconds`): its own last go, a wait for a turn aside, as one asked
for again after its suite said busy.  One the lander finds red keeps the length as it was,
though its suite passed: on a checkout it changed, or with a new test file over the piece
target; so does a piece alone.
Black-box: test_key_a_line_waits_for_company_by_its_own_checks_length.

In-process: `land._check` on a scratch checkout of test_landing_red_on_the_tip_pauses's
repository, a green length of 40 minutes on record before; where lengths are read, the clock
stands still but for each command's box and each turn asked for again.
"""

from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.clock import Clock
import test_lander as fixture
import test_landing_red_on_the_tip_pauses as tip
from test_suite_on_a_helper import Turn
from agentkit import gate, land, record, worker

KEPT = 40 * 60
QUEUED = 3600       # a turn asked for again after the first
SLOW = 'case "$AK_SHARD" in 1/*) echo "PASS  test_new.py (900s)";; esac'
SUITE, REWRITTEN, ONCE = "printf suite", "printf rewritten", "printf once"


class ALandingCheckKeepsEachCommandsGreenLength(unittest.TestCase):
    # that test's repository, through its class: its tests are not this file's
    setUp, prepare, commit, check, declare = (
        vars(tip.RedOnTheTip)[name] for name in ("setUp", "prepare", "commit", "check", "declare"))

    def checked(self, suite, commands=None, *, once="true", shard=None, files=None):
        """Whether the lander's check passes a member adding `files`, its task's once command
        `once`, where the target declares `suite`, and each command's green length after: the
        member's landing checks, or `commands`, each with KEPT on record before."""
        self.declare(suite)
        directory = fixture.Lander.member(self, "first", 1, once=once, **(files or {}))
        state = record.read_state(directory)
        with ExitStack() as opened, patch.object(gate, "derived_heavy_limit", return_value=3):
            checkout, error = land._scratch(self.repo, state["review"]["head_sha"], opened)
            self.assertFalse(error)
            commands = commands or list(land._landing_checks(directory, state, checkout,
                                                             self.base))
            gate.checked_green(self.repo, dict.fromkeys(commands, KEPT))
            ok = land._check(directory, state, checkout, commands, directory / "check.log",
                             lambda _: None, suite=suite, shard=shard)[0]
        return ok, {command: gate.green_seconds(command, self.repo) for command in commands}

    def test_each_command_keeps_its_own_last_go_its_waits_for_a_turn_aside(self):
        took, tick, turns = {SUITE: 120, REWRITTEN: 240, ONCE: 2400}, [0], []
        clock = Clock(lambda _seconds: None)
        clock.monotonic = lambda: tick[0]

        def box(argv, *_args, **_kw):
            if argv[-1] == SUITE and len(turns) < 2:    # busy on its first go
                return gate.SUITE_BUSY, "", False
            tick[0] += took[argv[-1]]
            return 0, "", False

        def turn(*_args, context=None, **_kw):
            tick[0] += QUEUED if turns else 0
            turns.append(Turn(1))
            turns[-1].context = context
            return turns[-1]

        with patch.object(worker, "boxed", side_effect=box), \
                patch.object(gate, "_acquire_gate_turn", side_effect=turn), \
                patch.object(land, "time", clock), patch.object(gate, "time", clock):
            self.assertEqual(self.checked(SUITE, once=ONCE, files={
                "AGENTS.md": f"---\ntests: {REWRITTEN}\n---\n"}), (True, took))
        self.assertEqual(len(turns), 2)

    def test_a_check_on_a_checkout_its_suite_changed_keeps_the_length(self):
        suite = "printf more >> base.txt"
        self.assertEqual(self.checked(suite, [suite]), (False, {suite: KEPT}))

    def test_a_check_refused_for_a_slow_new_test_keeps_the_length(self):
        self.assertEqual(self.checked(SLOW, [SLOW], files={"test_new.py": "x\n"}),
                         (False, {SLOW: KEPT}))

    def test_a_piece_alone_keeps_the_length(self):
        suite = ': "$AK_SHARD"; true'
        self.assertEqual(self.checked(suite, [suite], shard="1/2"), (True, {suite: KEPT}))


if __name__ == "__main__":
    unittest.main()
