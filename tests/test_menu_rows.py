"""The menu is projects, their sessions in the order they were made, and five keys; offline.

Fake checkouts, seats, run records and plan files, the real renderer. Nothing
touches a harness, tmux or the owner's own ~/.agentkit.
"""

from contextlib import redirect_stdout
import io
import os
import re
from unittest.mock import patch
import unittest

from fixtures.sandbox import REPO, Sandbox, menu_input
from agentkit import config, menu, notify, orch, run, terminal, watch
from agentkit import record as run_record

NOW = 1_800_000_000
DAY = 86400


class MenuRows(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=NOW))
        self.stack.enter_context(patch.object(menu.time, "strftime", return_value="14:02"))
        self.stack.enter_context(patch("agentkit.watch.live_state", side_effect=lambda seat, *a, **kw:
                                       {"state": seat.get("live", "at_prompt"), "rule": "fixture",
                                        "evidence": seat.get("asked", ""),
                                        "began": seat.get("since", NOW - 600),
                                        "since": seat.get("since", NOW - 600)}))
        for name in ("atoll", "agentkit"):
            (config.CODE / name / ".git").mkdir(parents=True)
        self.seats = []

    def seat(self, name, repo, live="at_prompt", since=NOW - 600, orchestrator="fable", **extra):
        path = str(config.CODE / repo) if repo else str(self.root)
        session = {"name": name, "repo": path if repo else None, "path": path,
                   "live": live, "since": since, "created": NOW - 5 * DAY, **extra}
        config.save_session(self.cfg, name, orchestrator, ["opus"],
                            {"repo": path if repo else None, "cwd": path})
        self.seats.append(session)
        return session

    def record(self, name, owner, **extra):
        directory = config.RUNS / name
        directory.mkdir(exist_ok=True)
        state = {"run_id": name, "title": f"Work {name}", "state": "pass",
                 "verdict": "PASS", "launched_session": owner, "reported": False,
                 "executor": "opus", "reviewer": "astra",
                 "finished_at": NOW - 1800, "started_at": NOW - 3600, **extra}
        run_record.save_state(directory, state)
        for path in list(directory.rglob("*")) + [directory]:
            try:
                if path.is_file() or path == directory:
                    os.utime(path, (NOW, NOW))
            except OSError:
                pass
        return directory

    def plan(self, name, done, total):
        lines = ["- [x] done"] * done + ["- [ ] todo"] * (total - done)
        (config.STATE / f"plan-{name}.md").write_text("\n".join(lines) + "\n")

    def draw(self, width=100, height=30, page=0, keys=menu.KEYS):
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=height), \
                redirect_stdout(io.StringIO()) as out:
            pagination = menu.draw(self.cfg, self.seats, keys, page)
        return out.getvalue(), pagination

    def test_seats_keep_their_place_whatever_their_word(self):
        self.seat("apple-working", "atoll", live="working")
        self.seat("middle-done", "atoll")
        config.plan_path("middle-done").write_text("- [x] hero swapped and published\n")
        self.seat("zebra-needs", "atoll")
        notify.record("zebra-needs", "needs", "Merge the MOV helper before or after?")
        screen, _ = self.draw(100, 30)
        self.assertLess(screen.index("apple-working"), screen.index("middle-done"))
        self.assertLess(screen.index("middle-done"), screen.index("zebra-needs"))
        # A seat's number is its place on the screen, in `found`'s order (`orch.numbered`).
        self.assertRegex(screen, r"1\s+apple-working\s+fable\s+● working")
        self.assertRegex(screen, r"2\s+middle-done\s+fable\s+✓ done")
        self.assertRegex(screen, r"3\s+zebra-needs\s+fable\s+! needs you")

    def test_projects_in_the_order_of_their_first_seat(self):
        self.seat("atoll-work", "atoll", live="working")
        self.seat("agentkit-need", "agentkit")
        notify.record("agentkit-need", "needs", "Which schema?")
        screen, _ = self.draw(100, 30)
        self.assertLess(screen.index("\natoll\n"), screen.index("\nagentkit\n"))
        # Headings are the basename in bold, no counts, no state words.
        self.assertNotIn("seats", screen)
        self.assertEqual(screen.count("needs you"), 1)

    def test_orchestrator_column(self):
        self.seat("first-seat", "atoll", orchestrator="fable")
        self.seat("second-seat", "atoll", orchestrator="astra")
        screen, _ = self.draw(100, 30)
        self.assertRegex(screen, r"first-seat\s+fable\s+[●!✓○]")
        self.assertRegex(screen, r"second-seat\s+astra\s+[●!✓○]")

    def test_narrow_rows_keep_readable_names_beside_or_above_the_state(self):
        for word in terminal.STATES:
            for width in range(20, 41):
                with self.subTest(word=word, width=width):
                    infos = [{"number": str(number), "name": name, "count": word,
                              "orchestrator": "astra"}
                             for number, name in ((1, "fix-api-checks"), (2, "fix-web-checks"))]
                    for info, block in zip(infos, menu.v5o_seat_blocks(infos, width)):
                        rows = [terminal.plain(line) for line in block]
                        self.assertIn(info["name"][:7], rows[0])
                        self.assertTrue(any(terminal.state_text(word) in row for row in rows), rows)
                        self.assertTrue(all(terminal.cells(line) <= width for line in block))

    def test_plan_bar_from_plan_file(self):
        seat = self.seat("fix-api", "atoll", live="working")
        self.plan("fix-api", 2, 5)
        self.record("fix-going", owner=seat["name"], repo=seat["repo"],
                    state="running", finished_at=None, started_at=NOW - 600,
                    rounds=2, round_summaries=[], **run_record.process_owner())
        screen, _ = self.draw(100, 30)
        row = next(line for line in screen.splitlines() if "fix-api" in line)
        # two of five merged, and the run going a quarter into the next, in the row's room
        self.assertRegex(row, r"● working  [━╸]+─+ 2 of 5$")
        self.assertEqual(terminal.cells(row), 100)
        self.assertNotIn("running", row)

    def test_no_bar_without_plan(self):
        # Working via a turn, no plan and no runs: the last column is empty.
        self.seat("lonely-work", "atoll", live="working")
        screen, _ = self.draw(100, 30)
        row = next(line for line in screen.splitlines() if "lonely-work" in line)
        self.assertTrue(row.rstrip().endswith("● working"), row)
        # A plan with zero tasks is no plan at all.
        (config.STATE / "plan-lonely-work.md").write_text("just notes\n")
        screen, _ = self.draw(100, 30)
        row = next(line for line in screen.splitlines() if "lonely-work" in line)
        self.assertTrue(row.rstrip().endswith("● working"), row)

    def test_reason_column_needs_you(self):
        self.seat("ask-seat", "atoll")
        notify.record("ask-seat", "needs", "Merge the MOV helper before or after?")
        gone = self.seat("gone-seat", "atoll", **{"exited": True})
        screen, _ = self.draw(100, 30)
        lines = screen.splitlines()
        # a row is its word; what it asks opens under it, as every row asking does from a pipe
        at = next(n for n, line in enumerate(lines) if "ask-seat" in line)
        self.assertTrue(lines[at].endswith("! needs you"), lines[at])
        self.assertEqual(lines[at + 1].strip(), "Merge the MOV helper before or after?")
        number = next(i for i, s in enumerate(self.seats, 1) if s["name"] == "gone-seat")
        at = next(n for n, line in enumerate(lines) if "gone-seat" in line)
        self.assertEqual(lines[at + 1].strip(), f"session closed: press {number} to reopen")
        self.assertNotIn("press r", screen)

    def test_reason_column_working(self):
        # Plan wins over runs; runs going are never the last column, which stays empty.
        planned = self.seat("planned-work", "atoll", live="working")
        self.plan("planned-work", 1, 3)
        self.record("planned-going", owner=planned["name"], repo=planned["repo"],
                    state="running", finished_at=None, started_at=NOW - 600,
                    rounds=2, round_summaries=[], **run_record.process_owner())
        running = self.seat("running-work", "atoll", live="working")
        self.record("run-one", owner=running["name"], repo=running["repo"],
                    state="running", finished_at=None, started_at=NOW - 600,
                    rounds=2, round_summaries=[], **run_record.process_owner())
        self.record("run-two", owner=running["name"], repo=running["repo"],
                    state="running", finished_at=None, started_at=NOW - 500,
                    rounds=2, round_summaries=[], **run_record.process_owner())
        idle = self.seat("idle-work", "atoll", live="working")
        screen, _ = self.draw(100, 30)
        self.assertRegex(next(line for line in screen.splitlines() if "planned-work" in line),
                         r"[━╸]+─+ 1 of 3$")
        row = next(line for line in screen.splitlines() if "running-work" in line)
        self.assertNotIn("2 running", row)
        self.assertTrue(row.rstrip().endswith("● working"))
        idle_row = next(line for line in screen.splitlines() if "idle-work" in line)
        self.assertTrue(idle_row.rstrip().endswith("● working"))

    def test_reason_column_done(self):
        self.seat("done-seat", "atoll")
        config.plan_path("done-seat").write_text("- [x] Earlier line here\n- [x] hero swapped and published\n")
        screen, _ = self.draw(100, 30)
        lines = screen.splitlines()
        at = next(n for n, line in enumerate(lines) if "done-seat" in line)
        self.assertIn("✓ done", lines[at])
        self.assertEqual(lines[at + 1].strip(), "hero swapped and published")
        self.assertNotIn("Earlier line", screen)

    def test_key_line_has_exactly_five_keys(self):
        self.seat("only-seat", "atoll", live="working")
        screen, pages = self.draw(100, 30)
        self.assertEqual(pages[1], 1)
        for phrase in ("n new", "x stop", "c config", "esc leave"):
            self.assertIn(phrase, screen)
        for gone in ("i info", "p preview", "b browser", "r runs", "j more", "k previous"):
            self.assertNotIn(gone, screen)
        # Two pages: paging appears, and only then.
        self.seats = []
        for n in range(12):
            self.seat(f"seat-{n:02d}", "atoll", live="working")
        screen, pages = self.draw(100, 10)
        self.assertGreater(pages[1], 1)
        self.assertIn("j more", screen)
        self.assertIn("k previous", screen)

    def test_removed_keys_answer_not_a_key(self):
        self.seat("only-seat", "atoll", live="working")
        with patch.object(orch, "listing", return_value=self.seats), \
                patch.object(orch, "job_notices", return_value=[]), \
                menu_input(side_effect=["r", "p", "b", "s", "u", ""]), \
                patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        screen = out.getvalue()
        for key in ("r", "p", "b", "s", "u"):
            self.assertIn(f"not a key: {key!r}", screen)



if __name__ == "__main__":
    unittest.main(verbosity=2)
