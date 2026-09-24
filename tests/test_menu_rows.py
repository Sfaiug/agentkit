"""The menu is projects, their sessions by state, and six keys; offline.

Fake checkouts, seats, run records and plan files, the real renderer. Nothing
touches a harness, tmux or the owner's own ~/.agentkit.
"""

from contextlib import redirect_stdout
import io
import os
import re
from unittest.mock import patch
import unittest

from test_v4n import REPO, Sandbox
from agentkit import config, menu, notify, orch, run, terminal, watch

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
        run.save_state(directory, state)
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

    def test_sort_order_by_state_within_a_project(self):
        self.seat("apple-working", "atoll", live="working")
        self.seat("middle-done", "atoll")
        notify.record("middle-done", "done", "hero swapped and published")
        self.seat("zebra-needs", "atoll")
        notify.record("zebra-needs", "needs", "Merge the MOV helper before or after?")
        screen, _ = self.draw(100, 30)
        self.assertLess(screen.index("zebra-needs"), screen.index("apple-working"))
        self.assertLess(screen.index("apple-working"), screen.index("middle-done"))
        # Numbers stay global by name order in `found`, not display order.
        self.assertRegex(screen, r"3\s+zebra-needs\s+fable\s+! needs you")
        self.assertRegex(screen, r"1\s+apple-working\s+fable\s+● working")
        self.assertRegex(screen, r"2\s+middle-done\s+fable\s+✓ done")

    def test_projects_with_needs_you_first(self):
        self.seat("atoll-work", "atoll", live="working")
        self.seat("agentkit-need", "agentkit")
        notify.record("agentkit-need", "needs", "Which schema?")
        screen, _ = self.draw(100, 30)
        self.assertLess(screen.index("\nagentkit\n"), screen.index("\natoll\n"))
        self.assertIn("your projects · 1 needs you", screen)
        # Headings are the basename in accent, no counts, no state words.
        self.assertNotIn("seats", screen)
        self.assertNotIn("needs you", screen.split("your projects")[0].rsplit("\n", 2)[0])

    def test_orchestrator_column(self):
        self.seat("first-seat", "atoll", orchestrator="fable")
        self.seat("second-seat", "atoll", orchestrator="astra")
        screen, _ = self.draw(100, 30)
        self.assertRegex(screen, r"first-seat\s+fable\s+[●!✓]")
        self.assertRegex(screen, r"second-seat\s+astra\s+[●!✓]")

    def test_plan_bar_from_plan_file(self):
        seat = self.seat("fix-api", "atoll", live="working")
        self.plan("fix-api", 2, 5)
        self.record("fix-going", owner=seat["name"], repo=seat["repo"],
                    state="running", finished_at=None, started_at=NOW - 600,
                    rounds=2, round_summaries=[], **run.process_owner())
        screen, _ = self.draw(100, 30)
        expected = f"tasks {terminal.progress_bar(2, 5)}"
        self.assertIn(expected, screen)
        self.assertIn("2/5", screen)
        row = next(line for line in screen.splitlines() if "fix-api" in line)
        self.assertIn("● working", row)
        self.assertIn("tasks ", row)
        self.assertNotIn("running", row.split("tasks ")[0].rsplit("working", 1)[-1])

    def test_no_bar_without_plan(self):
        # Working via a turn, no plan and no runs: the last column is empty.
        self.seat("lonely-work", "atoll", live="working")
        screen, _ = self.draw(100, 30)
        row = next(line for line in screen.splitlines() if "lonely-work" in line)
        self.assertNotIn("tasks ", row)
        self.assertNotIn("/", row)
        # A plan with zero tasks is no plan at all.
        (config.STATE / "plan-lonely-work.md").write_text("just notes\n")
        screen, _ = self.draw(100, 30)
        row = next(line for line in screen.splitlines() if "lonely-work" in line)
        self.assertNotIn("tasks ", row)

    def test_reason_column_needs_you(self):
        self.seat("ask-seat", "atoll")
        notify.record("ask-seat", "needs", "Merge the MOV helper before or after?")
        gone = self.seat("gone-seat", "atoll", **{"exited": True})
        screen, _ = self.draw(100, 30)
        ask = next(line for line in screen.splitlines() if "ask-seat" in line)
        self.assertIn("! needs you", ask)
        self.assertIn("Merge the MOV helper before or after?", ask)
        number = next(i for i, s in enumerate(self.seats, 1) if s["name"] == "gone-seat")
        row = next(line for line in screen.splitlines() if "gone-seat" in line)
        self.assertIn(f"session closed: press {number} to reopen", row)
        self.assertNotIn("press r", screen)

    def test_reason_column_working(self):
        # Plan wins over runs; runs win over empty.
        planned = self.seat("planned-work", "atoll", live="working")
        self.plan("planned-work", 1, 3)
        self.record("planned-going", owner=planned["name"], repo=planned["repo"],
                    state="running", finished_at=None, started_at=NOW - 600,
                    rounds=2, round_summaries=[], **run.process_owner())
        running = self.seat("running-work", "atoll", live="working")
        self.record("run-one", owner=running["name"], repo=running["repo"],
                    state="running", finished_at=None, started_at=NOW - 600,
                    rounds=2, round_summaries=[], **run.process_owner())
        self.record("run-two", owner=running["name"], repo=running["repo"],
                    state="running", finished_at=None, started_at=NOW - 500,
                    rounds=2, round_summaries=[], **run.process_owner())
        idle = self.seat("idle-work", "atoll", live="working")
        screen, _ = self.draw(100, 30)
        self.assertIn("tasks ", next(line for line in screen.splitlines() if "planned-work" in line))
        row = next(line for line in screen.splitlines() if "running-work" in line)
        self.assertIn("2 running", row)
        self.assertNotIn("tasks ", row)
        idle_row = next(line for line in screen.splitlines() if "idle-work" in line)
        self.assertTrue(idle_row.rstrip().endswith("● working"))

    def test_reason_column_done(self):
        self.seat("done-seat", "atoll")
        notify.record("done-seat", "done", "hero swapped and published\n\nSecond line here")
        screen, _ = self.draw(100, 30)
        row = next(line for line in screen.splitlines() if "done-seat" in line)
        self.assertIn("✓ done", row)
        self.assertIn("hero swapped and published", row)
        self.assertNotIn("Second line", row)

    def test_key_line_has_exactly_six_keys(self):
        self.seat("only-seat", "atoll", live="working")
        screen, pages = self.draw(100, 30)
        self.assertEqual(pages[1], 1)
        for phrase in ("n new", "x stop", "c config", "i info", "q leave"):
            self.assertIn(phrase, screen)
        for gone in ("p preview", "b browser", "r runs", "m more", "k previous"):
            self.assertNotIn(gone, screen)
        # Two pages: paging appears, and only then.
        self.seats = []
        for n in range(12):
            self.seat(f"seat-{n:02d}", "atoll", live="working")
        screen, pages = self.draw(100, 10)
        self.assertGreater(pages[1], 1)
        self.assertIn("m more", screen)
        self.assertIn("k previous", screen)

    def test_removed_keys_answer_not_a_key(self):
        self.seat("only-seat", "atoll", live="working")
        answers = iter(["r", "p", "b", "s", "u", "q"])
        with patch.object(orch, "listing", return_value=self.seats), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu, "read", side_effect=lambda *_: next(answers)), \
                patch.object(menu, "wait_key", side_effect=lambda prompt, timeout=None,
                             wake=None: menu.read(prompt, "q")), \
                patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        screen = out.getvalue()
        for key in ("r", "p", "b", "s", "u"):
            self.assertIn(f"not a key: {key!r}", screen)

    def test_info_screen_first_line(self):
        with redirect_stdout(io.StringIO()) as out:
            menu.show_info(dry_run=True)
        screen = out.getvalue()
        self.assertIn("agentkit: you talk to one orchestrator; it works until it is done or it needs you.",
                      screen)


if __name__ == "__main__":
    unittest.main(verbosity=2)
