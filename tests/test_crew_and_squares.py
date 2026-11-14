"""The line under a working row says who builds, who reviews, and each task as its squares.

The owner's design (14 Oct 2026): pointing at a working seat opens one line under its row --
`opus orchestrates   astra builds   fable reviews   ■□□  ■■□` -- the seat's orchestrator, then each
model once, what it does after it in words (their pick of 10 Nov 2026), dim as the row's
orchestrator, with each task in flight as three squares
(build, review, land), the stages it reached filled: in working's colour while a model or ak
works on it, dim while it waits; a run that ended is gone from it, whatever it delivered (their
word of 19 Oct 2026).  No task's name appears anywhere.
Offline: a temporary HOME, fake run records, no tmux.
"""

from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, record, terminal  # noqa: E402

SEAT = "acme-api"
NOW = 1_800_000_000


def run(name, **state):
    return Path(name), {"run_id": name, "launched_session": SEAT, "started_at": NOW - 600,
                        "task_file": f"/t/{name}.md", **state}


class CrewAndSquares(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))

    # each task in flight as three squares (build, review, land).
    # Reason: ended runs stayed red squares. [2, 14, 19, 23, 26 Oct 2026]
    def test_each_run_in_flight_is_a_task_at_its_stage_moving_or_waiting_and_an_ended_one_none(self):
        records = [
            run("g1-parser", state="running", step="executor"),
            run("g2-review", state="running", step="reviewer"),
            run("g3-merge", state="running", step="merge"),
            run("g4-queued", state="queued"),
            run("g5-line", state="waiting", waiting_on={"line": "main", "joined": NOW}),
            run("g6-failed", state="fail", verdict="FAIL", step="reviewer", handed_back=True,
                finished_at=NOW - 60),
            run("g7-merged", state="pass", merged=True, live_at=NOW - 30),
            run("g8-blocked", state="blocked", step="executor", finished_at=NOW - 60),
            run("g9-error", state="error", step="merge", finished_at=NOW - 60),
            run("other", state="running", step="executor", launched_session="other-seat"),
        ]
        self.assertEqual(menu.seat_tasks(SEAT, records, NOW), [
            (0, "moving"), (0, "waiting"), (1, "moving"), (2, "moving"), (2, "waiting")])

    def test_a_running_loop_that_only_waits_is_waiting(self):
        """Its pid on a transient wait not yet over, a suite turn or another delivery's turn."""
        records = [
            run("g1-retry", state="running", step="executor", pid=42,
                transient_wait={"until": NOW + 60, "pid": 42}),
            run("g2-retried", state="running", step="executor", pid=42,
                transient_wait={"until": NOW - 1, "pid": 42}),
            run("g3-suite", state="running", step="done-when", pid=42,
                gate_turn={"pid": 42, "of": "acme", "since": NOW}),
            run("g4-delivery", state="running", step="merge", pid=42, delivery_wait=42),
        ]
        with patch.object(record, "process_active", return_value=True):
            self.assertEqual(menu.seat_tasks(SEAT, records, NOW),
                             [(0, "moving"), (0, "waiting"), (0, "waiting"), (2, "waiting")])

    def test_squares_fill_the_stages_reached_and_count_what_does_not_fit(self):
        tasks = [(0, "moving"), (1, "waiting"), (2, "moving")]
        with patch.object(terminal, "colour_depth", return_value=0):
            self.assertEqual(menu.squares(tasks, 40), "■□□  ■■□  ■■■")
            self.assertEqual(menu.squares(tasks * 4, 21), "■□□  ■■□  ■■■  +9")
            # the count takes the cells its digits need, no more and no fewer
            self.assertEqual(menu.squares(tasks[:2], 7), "■□□  +1")
            self.assertEqual(menu.squares(tasks[:1] * 103, 8), "+103")
        with patch.dict(os.environ, {"LANG": "C", "LC_ALL": ""}), \
                patch.object(terminal, "colour_depth", return_value=0):
            self.assertEqual(menu.squares(tasks, 40), "#--  ##-  ###")
        with patch.object(terminal, "colour_depth", return_value=24):
            drawn = menu.squares(tasks, 40)
            working, dim = terminal.styled("■", "working"), terminal.styled("□", "dim")
            self.assertTrue(drawn.startswith(working + terminal.styled("□□", "dim")), drawn)
            self.assertIn(terminal.styled("■■", "dim") + dim, drawn)
            self.assertTrue(drawn.endswith(terminal.styled("■■■", "working")), drawn)

    def test_the_line_names_who_builds_and_reviews_and_never_a_task(self):
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"reviewers": ["fable"]})
        records = [run("g1-parser-rewrite", state="running", step="executor"),
                   run("g2-schema-switch", state="running", step="reviewer")]
        info = menu.v5o_seat_info(self.cfg, 1, {"name": SEAT, "created": NOW}, records, {},
                                  None, NOW)
        info["word"] = "working"
        with patch.object(terminal, "colour_depth", return_value=0):
            [line] = menu.detail(info, 100)
        self.assertEqual(line, "Opus 5.5 xhigh orchestrates   6 Astra xhigh builds   "
                               "Fable 5.1 xhigh reviews   ■□□  ■■□")
        self.assertNotIn("parser", line)
        # a model in two roles is named once, with both
        info["crew"] = ("opus", ["opus", "astra"], ["fable", "opus"])
        with patch.object(terminal, "colour_depth", return_value=0):
            self.assertTrue(menu.detail(info, 100)[0].startswith(
                "opus orchestrates, builds, reviews   astra builds   fable reviews   "))
        # the names are the colour of the row's orchestrator, their roles with them
        with patch.object(terminal, "colour_depth", return_value=24):
            self.assertEqual(menu.crew({"crew": ("opus", ["astra"], ["fable"])}),
                             terminal.styled("opus orchestrates   astra builds   fable reviews",
                                             "dim"))
        # a narrow line cuts the crew, never the squares
        info["crew"] = ("opus", ["astra", "opus"], ["fable", "spark"])
        info["tasks"] = [(0, "moving")]
        with patch.object(terminal, "colour_depth", return_value=0):
            self.assertEqual(menu.detail(info, 39),
                             ["opus orchestrates, builds   astr…   ■□□"])

    def test_an_orchestrator_building_alone_is_no_builder_on_the_line(self):
        """The owner's word of 21 Oct 2026: with no executor marked, no `builds` names the
        seat's own model, so the line differs from one whose executor is that same model."""
        records = [run("g1-parser", state="running", step="reviewer")]
        lines = {}
        for workers in ([], ["astra"]):
            config.save_session(self.cfg, SEAT, "astra", workers, {"reviewers": ["fable"]})
            info = menu.v5o_seat_info(self.cfg, 1, {"name": SEAT, "created": NOW}, records, {},
                                      None, NOW)
            info["word"] = "working"
            with patch.object(terminal, "colour_depth", return_value=0):
                [lines[bool(workers)]] = menu.detail(info, 80)
        self.assertEqual(lines, {
            False: "6 Astra xhigh orchestrates   Fable 5.1 xhigh reviews   ■■□",
            True: "6 Astra xhigh orchestrates, builds   Fable 5.1 xhigh reviews   ■■□"})


if __name__ == "__main__":
    unittest.main()
