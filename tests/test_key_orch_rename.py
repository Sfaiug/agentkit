"""`ak orch rename` gives a running seat a new name and carries everything that names it.

The orchestrator in a seat was started with its old name in $AGENTKIT_SESSION and hands that name
to every `ak` it runs, so a rename that left anything behind would split one seat in two: tmux,
the record, the seat's files and its runs' records all answer to the new name, and every old name
leads there.  `--auto` is how a seat opened without a name takes one, and only once.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py on seats from
tests/fixtures/akseat.py, and this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

PLAN = "# Plan\n\n- [x] read the parser\n- [ ] fix the parser\n"
NOTICE = {"kind": "done", "message": "parser fixed"}
TYPED = {"at": 1, "text": "fix the parser", "source": "ak", "harness": "claude",
         "conversation": "conv-alpha", "after": 0}
# Each file the seat keeps under its name, and whether a rename carries it to the new one.  The
# running harness keeps the rulebook it was started on, its hooks keep this turn's latch under
# the name they were started with, and a pane still starting reads the launch file it was given.
FILES = {"plan-{}.md": (PLAN, True), "notify-{}.json": (NOTICE, True),
         "input-{}.jsonl": (json.dumps(TYPED) + "\n", True),
         "title-{}.json": ({}, True), "hook-{}.json": ({}, True), "card-{}.json": ({}, True),
         "seat-{}.json": ({}, True), "stop-{}.json": ({}, False),
         "rulebook-{}.md": ("# Rules\n", False), "launch-{}.sh": ("#!/bin/sh\n", False)}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Rename(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def state(self, name):
        return self.home.path / ".agentkit" / "state" / name

    def record(self, name):
        return json.loads(self.state(f"session-{name}.json").read_text())

    def run_record(self, run):
        return json.loads((self.home.path / ".agentkit" / "runs" / run / "run.json").read_text())

    def tmux(self, *args):
        done = self.home.tmux(*args)
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def test_renaming_a_seat_renames_its_tmux_session_and_moves_its_record(self):
        seat = Seat(self.home, "acme")
        done = self.home.ak("orch", "rename", "acme", "lagoon")
        self.assertEqual((done.code, done.out), (0, "renamed acme -> lagoon\n"), done.err)
        held = self.tmux("list-sessions", "-F", "#{session_name}").split()
        self.assertIn("lagoon", held)
        self.assertNotIn("acme", held)
        # the same pane, still running and still ak's seat, under the new name
        self.assertEqual(self.tmux("display-message", "-p", "-t", seat.pane, "#{session_name}"),
                         "lagoon\n")
        self.assertEqual(self.tmux("show-options", "-v", "-t", "=lagoon:", "@ak_orch"), "1\n")
        # what a window opened in it later runs as
        self.assertEqual(self.tmux("show-environment", "-t", "=lagoon", "AGENTKIT_SESSION"),
                         "AGENTKIT_SESSION=lagoon\n")
        self.assertEqual(self.record("acme"), {"renamed": "lagoon"})
        moved = self.record("lagoon")
        for field in ("orchestrator", "workers", "cwd", "conversation"):
            with self.subTest(field=field):
                self.assertEqual(moved.get(field), seat.record[field])

    def test_a_rename_carries_the_seats_files_its_old_names_and_its_runs(self):
        Seat(self.home, "alpha")
        for pattern, (data, _) in FILES.items():
            self.home.write(f".agentkit/state/{pattern.format('alpha')}", data)
        self.home.write(".agentkit/state/session-older.json", {"renamed": "alpha"})
        self.home.write(".agentkit/runs/run-alpha/run.json",
                        {"run_id": "run-alpha", "state": "pass", "launched_session": "alpha",
                         "session": "alpha"})
        self.home.write(".agentkit/runs/run-gamma/run.json",
                        {"run_id": "run-gamma", "state": "pass", "launched_session": "gamma",
                         "session": "gamma"})
        done = self.home.ak("orch", "rename", "alpha", "beta")
        self.assertEqual((done.code, done.out), (0, "renamed alpha -> beta\n"), done.err)
        # every old name leads straight to the new one
        for old in ("alpha", "older"):
            with self.subTest(pointer=old):
                self.assertEqual(self.record(old), {"renamed": "beta"})
        self.assertNotIn("renamed", self.record("beta"))
        for pattern, (_, moves) in FILES.items():
            was, now = self.state(pattern.format("alpha")), self.state(pattern.format("beta"))
            with self.subTest(file=pattern.format("alpha"), moves=moves):
                self.assertEqual((was.exists(), now.exists()), (not moves, moves))
        self.assertEqual(self.state("plan-beta.md").read_text(), PLAN)
        self.assertEqual(json.loads(self.state("notify-beta.json").read_text()), NOTICE)
        typed = self.state("input-beta.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(typed[0]), TYPED)
        ran = self.run_record("run-alpha")
        self.assertEqual((ran["launched_session"], ran["session"]), ("beta", "beta"))
        other = self.run_record("run-gamma")
        self.assertEqual((other["launched_session"], other["session"]), ("gamma", "gamma"))

    def test_auto_names_an_unnamed_seat_from_inside_it_once(self):
        seat = Seat(self.home, "delta", record={"unnamed": True})
        self.home.write(".agentkit/state/plan-delta.md", PLAN)
        self.home.write(".agentkit/state/notify-delta.json", NOTICE)
        self.home.write(".agentkit/runs/run-delta/run.json",
                        {"run_id": "run-delta", "state": "pass", "launched_session": "delta"})
        inside = {"AGENTKIT_SESSION": "delta"}
        done = self.home.ak("orch", "rename", "--auto", "Parser Fix", env=inside)
        self.assertEqual((done.code, done.out), (0, "renamed delta -> parser-fix\n"), done.err)
        self.assertEqual(self.tmux("display-message", "-p", "-t", seat.pane, "#{session_name}"),
                         "parser-fix\n")
        self.assertEqual(self.tmux("show-environment", "-t", "=parser-fix", "AGENTKIT_SESSION"),
                         "AGENTKIT_SESSION=parser-fix\n")
        self.assertEqual(self.record("delta"), {"renamed": "parser-fix"})
        named = self.record("parser-fix")
        self.assertNotIn("unnamed", named)
        self.assertEqual(named["conversation"], "conv-delta")
        for old, new in (("plan-delta.md", "plan-parser-fix.md"),
                         ("notify-delta.json", "notify-parser-fix.json")):
            with self.subTest(file=old):
                self.assertEqual((self.state(old).exists(), self.state(new).exists()),
                                 (False, True))
        self.assertEqual(self.run_record("run-delta")["launched_session"], "parser-fix")
        # The orchestrator inside still carries its first name: it reaches the seat, now named.
        again = self.home.ak("orch", "rename", "--auto", "Lexer Fix", env=inside)
        self.assertEqual((again.code, again.out), (0, "seat is already named parser-fix\n"),
                         again.err)
        self.assertEqual(self.record("delta"), {"renamed": "parser-fix"})
        self.assertFalse(self.state("session-lexer-fix.json").exists())

    def test_a_seat_renamed_back_to_a_name_it_had_takes_its_record_back_there(self):
        Seat(self.home, "kappa")
        for old, new in (("kappa", "sigma"), ("sigma", "kappa")):
            done = self.home.ak("orch", "rename", old, new)
            self.assertEqual((done.code, done.out), (0, f"renamed {old} -> {new}\n"), done.err)
        self.assertEqual(self.record("sigma"), {"renamed": "kappa"})
        self.assertEqual(self.record("kappa")["conversation"], "conv-kappa")
        # an old name given as OLD is the seat it leads to
        done = self.home.ak("orch", "rename", "sigma", "omega")
        self.assertEqual((done.code, done.out), (0, "renamed kappa -> omega\n"), done.err)
        for old in ("kappa", "sigma"):
            with self.subTest(pointer=old):
                self.assertEqual(self.record(old), {"renamed": "omega"})


if __name__ == "__main__":
    unittest.main()
