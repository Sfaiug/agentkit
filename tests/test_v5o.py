"""v5o: the menu at rest answers one question and reads at every width; offline.

Fixed fake state, the real renderer. The clock is pinned so the three snapshots
match byte for byte. See docs/cli-design.md for the visual system.
"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import sys
import time
from unittest.mock import patch
import unittest

from test_v4n import REPO, Sandbox
from agentkit import config, menu, orch, run, terminal, watch

NOW = 1_800_000_000
DAY = 86400
# `need you` is said once, on the top line: no other line of the menu at rest says
# it, so the fixture's needing seats read their own reason in the last column.
LONG_TITLE = ("Rebuild the dashboard filters so archived runs stay hidden "
              "until there are more than twenty of them")


class V5oMenu(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=NOW))
        self.stack.enter_context(patch("agentkit.watch.live_state", side_effect=lambda seat, *a, **kw:
                                      {"state": seat.get("live", "working"), "rule": "fixture",
                                       "since": seat.get("since"), "began": seat.get("since"),
                                       "evidence": seat.get("asked", "")}))
        self.stack.enter_context(patch.object(menu.time, "strftime", return_value="14:02"))
        # Two checkouts, and one directory under ~/code that is none: `checkouts()`
        # asks for a .git, and only a checkout is ever a project.
        for name in ("atoll", "agentkit"):
            (config.CODE / name / ".git").mkdir(parents=True)
        (config.CODE / "not-a-checkout").mkdir(parents=True)
        self.seats = []
        # v5ay: a run under a live seat hands its ending back to that seat, so the two seats
        # whose rows name a run of their own are ones nobody is in any more -- the hand-back
        # had nowhere to go, which is what makes the ending his.
        for name, repo, live, since, gone in (
                ("atoll-job", "atoll", "working", NOW - 900, False),
                ("atoll-solo", "atoll", "working", NOW - 800, False),
                ("herdr-quiet", "agentkit", "at_prompt", NOW - 3600, True),
                ("herdr-long", "agentkit", "working", NOW - DAY, False),
                ("scribe", None, "at_prompt", NOW - 3600, True)):
            path = str(config.CODE / repo) if repo else str(self.root)
            self.seats.append({"name": name, "repo": path if repo else None, "path": path,
                               "live": live, "since": since, "created": NOW - 5 * DAY,
                               **({"exited": True} if gone else {})})
            config.save_session(self.cfg, name, "fable", ["opus"],
                                {"repo": path if repo else None, "cwd": path})
        self.touching("job-run-1", owner="atoll-job", repo=str(config.CODE / "atoll"),
                      title="Rebuild the dashboard filters", state="running",
                      finished_at=None, started_at=NOW - 900, rounds=3,
                      round_summaries=[{}], executor="opus")
        self.touching("job-run-2", owner="atoll-job", repo=str(config.CODE / "atoll"),
                      title=LONG_TITLE, state="running",
                      finished_at=None, started_at=NOW - 800, rounds=3,
                      round_summaries=[{}], executor="astra")
        self.touching("solo-run-1", owner="atoll-solo", repo=str(config.CODE / "atoll"),
                      title="Fix the parser edge case", state="running",
                      finished_at=None, started_at=NOW - 700, rounds=2,
                      round_summaries=[], executor="opus")
        # A run of nobody's, with no repo at all: no project, no row, nobody's count.
        self.touching("orphan-unfinished", owner=None, repo=None,
                      title="Old unfinished work", state="interrupted",
                      started_at=NOW - DAY, interrupted_at=NOW - 80000,
                      recovery_pending=True, finished_at=None)
        # A run going under a seat that was stopped: still no row.
        self.touching("orphan-going", owner="stopped-seat", repo=str(config.CODE / "atoll"),
                      title="Orphan going fine", state="running", finished_at=None,
                      started_at=NOW - 300, rounds=2, round_summaries=[], executor="opus")
        # The smoke suite's throwaway repo under ~/.agentkit/tmp, and a run whose repo
        # is a worktree: neither is a checkout, so neither can ever be a project.
        self.touching("tmp-repo-run", owner="tmp-seat", repo=str(config.TMP / "smoke-repo"),
                      title="Throwaway smoke work", state="running", finished_at=None,
                      started_at=NOW - 600, rounds=2, round_summaries=[], executor="opus")
        self.touching("worktree-repo-run", owner="gone-seat",
                      repo=str(config.WT / "20260901-0101-old-work"),
                      title="Work in a worktree", state="fail", verdict="FAIL",
                      finished_at=NOW - 2 * DAY, started_at=NOW - 2 * DAY - 1800)
        # Under atoll-solo: a run parked on a provider window. It resumes itself, so the
        # seat keeps reading `1 running` and needs nobody.
        self.touching("solo-parked", owner="atoll-solo", repo=str(config.CODE / "atoll"),
                      title="Parked on a window", state="exhausted", quota_dry=True,
                      error="provider quota spent", finished_at=None,
                      started_at=NOW - 4 * 3600, rounds=2, round_summaries=[])
        # Under herdr-quiet: an eight-day-old failure that has aged out, and this week's
        # interruption, which is the one the row names.
        self.touching("idle-old-fail", owner="herdr-quiet", repo=str(config.CODE / "agentkit"),
                      title="Aged-out failure", state="fail", verdict="FAIL",
                      finished_at=NOW - 8 * DAY, started_at=NOW - 8 * DAY - 1800)
        self.touching("stopped-run", owner="herdr-quiet", repo=str(config.CODE / "agentkit"),
                      title="Stopped mid-round", state="interrupted", finished_at=None,
                      started_at=NOW - 2 * DAY, interrupted_at=NOW - 2 * DAY,
                      recovery_pending=True)
        # Under scribe: this week's failure, which is his to look at.
        self.touching("scribe-fail", owner="scribe", repo=None, title="Scribe failure",
                      state="fail", verdict="FAIL", finished_at=NOW - 2 * DAY,
                      started_at=NOW - 2 * DAY - 1800)
        self.touching("merged-hidden", owner="atoll-job", repo=str(config.CODE / "atoll"),
                      title="Shipped dashboard filters", state="pass", merged=True,
                      finished_at=NOW - 3600, started_at=NOW - 5400)
        jobs = config.HOME / "jobs" / "atoll-job"
        jobs.mkdir(parents=True, exist_ok=True)
        tasks = [{"status": "merged"}] * 2 + [{"status": "passed"}] + [{"status": "todo"}] * 4
        (jobs / "job.json").write_text(json.dumps({"seat": "atoll-job", "tasks": tasks}))
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": NOW, "providers": {
            "anthropic": {"meters": [{"name": "weekly_all", "used": 79}]},
            "openai": {"meters": [{"name": "weekly", "used": 31, "window_secs": 604800}], "resets": 2},
            "meta": {"meters": [{"name": "weekly", "used": 50, "window_secs": 604800}]}}}))
        self.needs_patch = patch.object(menu.notify, "last", return_value=None)
        self.stack.enter_context(self.needs_patch)

    def touching(self, name, owner="gone-seat", **extra):
        directory = config.RUNS / name
        directory.mkdir(exist_ok=True)
        state = {"run_id": name, "title": f"Finished {name}", "state": "pass",
                 "verdict": "PASS", "launched_session": owner, "reported": False,
                 "executor": "opus", "reviewer": "astra",
                 "finished_at": NOW - 1800, "started_at": NOW - 3600, **extra}
        if owner in ("atoll-job", "atoll-solo") and state.get("state") in ("running", "queued"):
            state.update(run.process_owner())
        run.save_state(directory, state)
        for path in list(directory.rglob("*")) + [directory]:
            try:
                if path.is_file() or path == directory:
                    os.utime(path, (NOW, NOW))
            except OSError:
                pass
        return directory

    def draw(self, width=100, height=30, page=0, keys=menu.KEYS):
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=height), \
                redirect_stdout(io.StringIO()) as out:
            pagination = menu.draw(self.cfg, self.seats, keys, page)
        return out.getvalue(), pagination

    def test_v5o_a_needs_line_and_needing_first(self):
        screen, _ = self.draw(100, 30)
        # The question is answered once, on the top line, and on no other line.
        self.assertIn("your projects · 2 need you", screen)
        self.assertNotIn("nothing needs you", screen)
        # The top line says it once, and each needing row says its own word.
        self.assertEqual(len(re.findall(r"need you|needs you", screen)), 3)
        # Needing rows first: the needing projects sort before the quiet one.
        self.assertLess(screen.index("\nagentkit\n"), screen.index("\natoll\n"))
        self.assertLess(screen.index("\nno project\n"), screen.index("\natoll\n"))
        # Each needing row carries its number and its one-line reason.
        self.assertRegex(screen, r"3\s+herdr-quiet\s+fable\s+! needs you\s+session closed: press 3")
        self.assertRegex(screen, re.compile(r"4\s+herdr-long\s+fable\s+● working\s*$", re.M))
        self.assertRegex(screen, r"5\s+scribe\s+fable\s+! needs you\s+session closed: press 5")
        # Nothing needs you when nothing does.
        with patch("agentkit.watch.live_state", return_value={"state": "working", "rule": "fixture",
                                                             "since": NOW - 60, "began": NOW - 60}):
            with patch.object(menu.notify, "last", return_value=None):
                for run_dir in run.run_dirs():
                    state = run.read_state(run_dir) or {}
                    if run.needs_recovery(state) or state.get("state") in ("fail", "error"):
                        state["recovery_acknowledged_at"] = NOW
                        run.save_state(run_dir, state)
                    if state.get("state") in ("running", "queued"):
                        state["state"] = "pass"
                        state["merged"] = True
                        state["finished_at"] = NOW - 60
                        run.save_state(run_dir, state)
                        for path in list(run_dir.rglob("*")):
                            try:
                                if path.is_file():
                                    os.utime(path, (NOW, NOW))
                            except OSError:
                                pass
                # Every seat on a turn of its own, and no problem run left: nothing is his.
                quiet = [{"name": s["name"], "repo": s["repo"], "path": s["path"],
                          "live": "working", "since": NOW - 60, "created": s["created"]}
                         for s in self.seats]
                # Re-draw with idle seats and no problem runs.
                with patch.object(terminal, "width", return_value=100), \
                        patch.object(terminal, "height", return_value=30), \
                        redirect_stdout(io.StringIO()) as out:
                    menu.draw(self.cfg, quiet)
                self.assertIn("nothing needs you", out.getvalue())

    def test_v5o_b_no_seat_row_wider_than_100_on_170(self):
        screen, _ = self.draw(170, 30)
        room = terminal.content_width(170)
        self.assertEqual(room, 100)
        seat_lines = [line for line in screen.splitlines()
                      if re.match(r"^\s+\d+\s+\S+", line)]
        self.assertTrue(seat_lines)
        for line in seat_lines:
            self.assertLessEqual(terminal.cells(terminal.plain(line)), 100, line)

    def test_v5o_c_sentence_wraps_word_boundaries(self):
        # A working seat without a plan reads its unfinished job's bar: short, never wrapped.
        screen, _ = self.draw(100, 30)
        job = next(line for line in screen.splitlines() if "atoll-job" in line)
        self.assertIn("tasks ", job)
        self.assertNotIn("2 running", job)
        # A last column too long for two lines is cut with … on the continuation.
        info = {"number": "1", "name": "atoll-job", "count": "needs you",
                "orchestrator": "fable", "worker": "fable",
                "sentence": "word " * 120, "bar": None, "running": 0,
                "word": "needs you"}
        lines = menu.v5o_format_seats([info], 100)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].strip().endswith("…"))
        # Wrapping never splits a word: the break is at a space.
        self.assertNotRegex(lines[0], r"\S…$")
        narrow = menu.v5o_format_seats([info], 40)
        self.assertGreaterEqual(len(narrow), 2)
        self.assertTrue(any("…" in line for line in narrow))

    def test_v5o_d_long_turn_plan_and_no_plan_rows(self):
        screen, _ = self.draw(100, 30)
        # A seat on a long turn with no plan and no runs reads empty, never another task.
        long_turn = next(line for line in screen.splitlines() if "herdr-long" in line)
        self.assertTrue(long_turn.rstrip().endswith("● working"))
        self.assertNotIn("Fix the", long_turn)
        # Runs going without a plan or a job read empty, never `N running`.
        quiet = next(line for line in screen.splitlines() if "atoll-solo" in line)
        self.assertTrue(quiet.rstrip().endswith("● working"))
        # A working seat without a plan reads its unfinished job's bar, the orchestrator,
        # no title.
        job = next(line for line in screen.splitlines() if "atoll-job" in line)
        self.assertRegex(job, r"tasks █+░+\s+3/7")
        self.assertIn("fable", job)
        self.assertNotIn("Rebuild the dashboard filters", screen)
        # A plan draws the bar; without a plan or a job there is no bar and no fake one.
        (config.STATE / "plan-atoll-job.md").write_text("- [x] a\n- [x] b\n- [x] c\n"
                                                        "- [ ] d\n- [ ] e\n- [ ] f\n"
                                                        "- [ ] g\n")
        screen, _ = self.draw(100, 30)
        self.assertIn("tasks ", screen)
        self.assertIn("3/7", screen)
        self.assertRegex(screen, r"tasks █+░+\s+3/7")
        solo_idx = screen.index("atoll-solo")
        solo_block = screen[solo_idx:solo_idx + 300]
        self.assertNotIn("2 running", solo_block)
        self.assertNotIn("tasks ", solo_block)
        self.assertNotIn("0/0", solo_block)
        solo_lines = [line for line in screen.splitlines() if "atoll-solo" in line]
        self.assertTrue(solo_lines and "/" not in solo_lines[0])

    def test_v5o_e_seats_only_never_a_run_row(self):
        screen, _ = self.draw(100, 30)
        # No `↳` row, ever: not a running one, not a failed one, not an orphan.
        self.assertNotIn("↳", screen)
        # A working seat never reads `N running`; no title is ever a row.
        self.assertNotIn("2 running", screen)
        # A merged run, an orphan and a run of a throwaway or worktree repo are
        # none of them a row, and none of them a project.
        for title in ("Rebuild the dashboard filters", "Shipped dashboard filters",
                      "Old unfinished work", "Orphan going fine", "Throwaway smoke work",
                      "Work in a worktree", "Parked on a window", "Aged-out failure",
                      "Scribe failure"):
            self.assertNotIn(title, screen)
        for heading in ("scratch", "smoke-repo", "20260901-0101-old-work"):
            self.assertNotIn(heading, screen)
        # Only the checkouts under ~/code, and the fallback for a seat with no repo.
        headings = [line for line in screen.splitlines()
                    if line in ("atoll", "agentkit", "no project")]
        self.assertEqual(headings, ["agentkit", "no project", "atoll"])

    def test_v5o_f_forbidden_words_absent(self):
        for width in (40, 100, 170):
            screen, _ = self.draw(width, 30 if width != 40 else 24)
            # No word outside the three is ever a state on this screen.
            for word in ("idle", "asking", "draft unsent", "stuck", "exited", "resumable",
                         "starts fresh", "legacy", "needs login", "unfinished",
                         "needs a look", "waiting for you"):
                for line in screen.splitlines():
                    self.assertNotIn(f" {word}", line, line)
            self.assertNotIn("merged", screen)
            self.assertNotIn("opus/astra", screen)
            # Never a done message on a seat row.
            self.assertNotIn("PASS", screen)
            self.assertNotIn("done", screen.lower().replace("needs you", ""))

    def test_v5o_g_header_is_the_basename_in_accent_and_nothing_else(self):
        screen, _ = self.draw(100, 30)
        for name in ("atoll", "agentkit", "no project"):
            self.assertIn(f"\n{name}\n", screen)
            line = next(line for line in screen.splitlines() if line == name)
            self.assertEqual(line, name)
            self.assertNotIn("needs you", line)
            self.assertNotIn("●", line)
            self.assertNotIn("○", line)
            self.assertNotIn("seats", line)
            self.assertNotIn("seat", line)
        with patch.object(terminal, "colour_depth", return_value=24):
            coloured, _ = self.draw(100, 30)
        self.assertIn(terminal.styled("agentkit", "accent"), coloured)
        self.assertIn(terminal.styled("atoll", "accent"), coloured)

    def test_v5o_h_superseded_is_not_a_row(self):
        failed = self.touching("old-first-pass", owner="atoll-solo",
                               repo=str(config.CODE / "atoll"), title="Superseded title",
                               state="fail", verdict="FAIL", finished_at=NOW - 3 * 3600,
                               started_at=NOW - 3 * 3600 - 1800)
        merged = self.touching("new-merged-pass", owner="atoll-solo",
                               repo=str(config.CODE / "atoll"), title="Superseded title",
                               state="pass", merged=True, finished_at=NOW - 3600,
                               started_at=NOW - 3600 - 1800)
        records = [run.read_state(d) for d in run.run_dirs()]
        self.assertEqual(run.superseded_by(run.read_state(failed), records), "new-merged-pass")
        self.assertTrue(run.is_superseded(run.read_state(failed), records))
        self.assertFalse(run.is_superseded(run.read_state(merged), records))
        screen, _ = self.draw(100, 30)
        self.assertNotIn("old-first-pass", screen)
        # Not in the reason either: the solo seat is still working, not needing him.
        solo = next(line for line in screen.splitlines() if "atoll-solo" in line)
        self.assertIn("● working", solo)
        # The table still says superseded by for whoever reads runs by id.
        found = list(menu.run_records())
        by_name = {d.name: s for d, s in found}
        self.assertIn("old-first-pass", by_name)
        blocks = menu.run_blocks(found, 100, 20)
        flat = "\n".join(line for block in blocks for line in block)
        self.assertIn("superseded by new-merged-pass", flat)

    def test_v5o_i_snapshots_match_byte_for_byte(self):
        for width, height in ((40, 30), (100, 30), (170, 30)):
            screen, _ = self.draw(width, height)
            self.assertEqual(screen, (REPO / f"tests/fixtures/v5o-{width}.txt").read_text())

    def test_v5o_j_silent_run_says_so(self):
        silent = self.touching("silent-run", owner="atoll-solo",
                               repo=str(config.CODE / "atoll"), title="Silent gate work",
                               state="running", finished_at=None, started_at=NOW - 3 * 3600,
                               rounds=2, round_summaries=[{}], executor="opus")
        for path in silent.rglob("*"):
            try:
                if path.is_file():
                    os.utime(path, (NOW - 2 * 3600, NOW - 2 * 3600))
            except OSError:
                pass
        fresh = self.touching("fresh-run", owner="atoll-solo",
                              repo=str(config.CODE / "atoll"), title="Fresh work",
                              state="running", finished_at=None, started_at=NOW - 600,
                              rounds=2, round_summaries=[], executor="opus")
        screen, _ = self.draw(100, 30)
        # The menu reads no `N running`; the state function keeps silent for `ak orch why`.
        self.assertNotIn("4 running", screen)
        self.assertNotIn("silent 2h", screen)
        self.assertNotIn("Silent gate work", screen)
        found = watch.session_state("atoll-solo", NOW, cfg=self.cfg,
                                    session=next(s for s in self.seats
                                                 if s["name"] == "atoll-solo"))
        self.assertRegex(found["reason"], r"silent 2h")
        self.assertIn("Silent gate work", found["reason"])
        # Under an hour nothing changes: the fresh run keeps its working count.
        self.assertNotIn("silent 0", screen)
        self.assertNotIn("silent <1m", screen)

    def test_v5o_q_endings_acknowledge_but_never_reach_a_row(self):
        # The fixture's own interruption is out of the way: this is about the endings below.
        run.acknowledge(config.RUNS / "stopped-run")
        failed = self.touching("herdr-first-pass", owner="herdr-quiet",
                               repo=str(config.CODE / "agentkit"), title="Herdr first pass",
                               state="fail", verdict="FAIL", finished_at=NOW - 3 * 3600,
                               started_at=NOW - 3 * 3600 - 1800)
        screen, _ = self.draw(100, 30)
        # The gone seat names its own number; no ending ever is the reason.
        self.assertNotIn("Herdr first pass", screen)
        self.assertRegex(screen, r"3\s+herdr-quiet\s+fable\s+! needs you\s+session closed: press 3")
        self.assertNotIn("press r", screen)
        # ak run status <id> marks an ending looked at, and acknowledge does.
        second = self.touching("herdr-second-pass", owner="herdr-quiet",
                               repo=str(config.CODE / "agentkit"), title="Herdr second pass",
                               state="fail", verdict="FAIL", finished_at=NOW - 2 * 3600,
                               started_at=NOW - 2 * 3600 - 1800)
        with redirect_stdout(io.StringIO()):
            run.cmd_status(["herdr-second-pass"])
        self.assertTrue(run.read_state(second).get("recovery_acknowledged_at"))
        third = self.touching("herdr-third-pass", owner="herdr-quiet",
                              repo=str(config.CODE / "agentkit"), title="Herdr third pass",
                              state="error", finished_at=NOW - 3600,
                              started_at=NOW - 3600 - 1800)
        run.acknowledge(third)
        fourth = self.touching("herdr-fourth-pass", owner="herdr-quiet",
                               repo=str(config.CODE / "agentkit"), title="Herdr fourth pass",
                               state="pass", verdict="PASS", finished_at=NOW - 4 * 3600,
                               started_at=NOW - 4 * 3600 - 1800)
        screen, _ = self.draw(100, 30)
        self.assertIn("session closed: press 3 to reopen", screen)
        self.assertNotIn("press r", screen)
        with redirect_stdout(io.StringIO()):
            run.cmd_status(["herdr-fourth-pass"])
        self.assertTrue(run.read_state(fourth).get("recovery_acknowledged_at"))
        for run_id in ("herdr-second-pass", "herdr-third-pass", "herdr-fourth-pass"):
            state = run.read_state(config.RUNS / run_id)
            self.assertTrue(state.get("recovery_acknowledged_at"), run_id)
        # Acknowledged or not, the gone seat is his for nobody being in it.
        screen, _ = self.draw(100, 30)
        self.assertNotIn("press r", screen.split("no project")[0])
        self.assertRegex(screen, re.compile(
            r"^\s*3\s+herdr-quiet\s+fable\s+! needs you\s+session closed: press 3 to reopen$", re.M))

    def test_v5o_k_frame_header_rule_keys_prompt_no_hash(self):
        screen, _ = self.draw(100, 30)
        lines = screen.splitlines()
        self.assertIn("agentkit", lines[0])
        self.assertIn("14:02", lines[0])
        self.assertTrue(set(lines[1]) <= set("─"))
        self.assertEqual(len(lines[1]), terminal.layout_width(100))
        self.assertIn("n new", lines[-1])
        self.assertIn("q leave", lines[-1])
        for phrase in menu.KEYS.split("   "):
            self.assertIn(phrase, screen)
        self.assertNotIn("8599bf1", screen)
        self.assertNotIn("3de8bef", screen)
        text = (REPO / "agentkit/menu.py").read_text()
        self.assertIn('"> "', text)

    def test_v5o_l_170_no_line_past_120_no_cut_glyph(self):
        screen, _ = self.draw(170, 30)
        for line in screen.splitlines():
            self.assertLessEqual(terminal.cells(line), 120, line)
            self.assertLessEqual(terminal.cells(terminal.plain(line)), 120, line)
        # No glyph or escape sequence is cut, with colour forced on: every opener
        # completes, so the ANSI count and the opener count agree on every line.
        # The ghost seat's `resumable` (it holds an `m`) rides along: counting
        # content letters as terminators would fail on that word alone.
        ghost = {"name": "ghost-seat", "repo": self.seats[0]["repo"],
                 "path": self.seats[0]["path"], "live": "at_prompt", "since": NOW - 60,
                 "created": NOW - 5 * DAY, "resumable": True}
        with patch.object(terminal, "colour_depth", return_value=24), \
                patch.object(terminal, "width", return_value=170), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats + [ghost])
        coloured = out.getvalue()
        self.assertIn("session closed: press 6 to reopen", coloured)
        for line in coloured.splitlines():
            self.assertEqual(line.count("\x1b["), len(terminal.ANSI.findall(line)), line)
            self.assertLessEqual(terminal.cells(terminal.plain(line)), 120, line)
        seat_lines = [line for line in screen.splitlines() if re.match(r"^\s+\d+\s+\S+", line)]
        for line in seat_lines:
            self.assertLessEqual(terminal.cells(terminal.plain(line)), 100, line)

    def test_v5o_m_40_no_age_alone_two_line_seat(self):
        screen, _ = self.draw(40, 30)
        for line in screen.splitlines():
            self.assertLessEqual(terminal.cells(line), 40, line)
            self.assertNotRegex(line, r"^\s*\d+[smhd]\s*$")
        # A seat row is two lines on a phone: head plus its last column indented.
        idx = next(i for i, line in enumerate(screen.splitlines()) if "atoll-job" in line)
        self.assertTrue(screen.splitlines()[idx + 1].startswith("    "))
        self.assertIn("tasks ", screen.splitlines()[idx + 1])

    def test_v5o_n_no_age_in_seconds(self):
        for width in (40, 100, 170):
            screen, _ = self.draw(width, 30 if width != 40 else 24)
            self.assertNotRegex(screen, r"\b\d+s\b")
            for line in screen.splitlines():
                # Ages read <1m, 5m, 2h, 3d.
                for found in re.findall(r"\b\d+[mhd]\b", line):
                    self.assertNotIn("s", found)

    def test_v5o_o_states_come_from_table(self):
        # The table is the single source, and it holds the whole vocabulary: every
        # word resolves through state_text and state_colour to its entry.
        self.assertEqual(list(terminal.STATES), ["working", "needs you", "done"])
        for word, (mark, colour) in terminal.STATES.items():
            self.assertTrue(mark)
            self.assertIn(colour, ("attention", "good", "accent"))
            self.assertEqual(terminal.state_text(word), f"{mark} {word}")
            self.assertEqual(terminal.state_colour(word), colour)
        self.assertEqual(terminal.STATES["working"][0], "●")
        self.assertEqual(terminal.STATES["needs you"][0], "!")
        self.assertEqual(terminal.STATES["done"][0], "✓")
        # ...and the screen shows the table's renderings and nothing else.
        screen, _ = self.draw(100, 30)
        for rendered in ("! needs you", "● working"):
            self.assertIn(rendered, screen)
        # `ak run status` reads the same table, and a run parked on a window is working.
        parked = next(state for d, state in menu.run_records()
                      if d.name == "solo-parked")
        self.assertEqual(menu.runs_word(parked), "working")
        ghost = {"name": "ghost-seat", "repo": self.seats[0]["repo"],
                 "path": self.seats[0]["path"], "live": "at_prompt", "since": NOW - 60,
                 "created": NOW - 5 * DAY, "resumable": True}
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats + [ghost])
        self.assertIn(terminal.state_text("needs you"), out.getvalue())
        text = (REPO / "agentkit/menu.py").read_text()
        self.assertIn("terminal.STATES", text)
        self.assertIn("terminal.state_text", text)
        self.assertIn("terminal.state_colour", text)

    def test_v5o_p_design_doc_names_every_helper(self):
        doc = (REPO / "docs/cli-design.md").read_text()
        self.assertTrue(doc.strip())
        for helper in ("header_line", "rule_line", "key_line", "layout_width",
                       "cut", "wrap", "pad", "cells", "plain", "styled",
                       "state_text", "state_colour", "progress_bar",
                       "format_age", "STATES"):
            self.assertIn(helper, doc, helper)
            self.assertIn(helper, (REPO / "agentkit/menu.py").read_text(), helper)
            self.assertIn(helper, (REPO / "agentkit/terminal.py").read_text(), helper)

    def test_v5o_r_gone_seat_with_conversation_keeps_its_row(self):
        # What orch.listing offers, the menu draws: a seat whose tmux instance is
        # gone keeps its row, marked with its lifecycle word, and its number opens
        # the conversation where it stopped.
        ghost = {"name": "ghost-seat", "repo": self.seats[0]["repo"],
                 "path": self.seats[0]["path"], "live": "at_prompt", "since": NOW - 60,
                 "created": NOW - 5 * DAY, "resumable": True}
        found = self.seats + [ghost]
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            pagination = menu.draw(self.cfg, found)
        screen = out.getvalue()
        self.assertEqual(pagination, (0, 1))
        row = next(line for line in screen.splitlines() if "ghost-seat" in line)
        self.assertRegex(row, r"^\s*6  ghost-seat\s+\S+\s+! needs you.*session closed: press 6")
        # The live rows are untouched, and every number is still global.
        self.assertIn("atoll-job", screen)
        numbers = sorted(int(m.group(1)) for line in screen.splitlines()
                         for m in [re.match(r"^\s*(\d+)  \S", line)] if m)
        self.assertEqual(numbers, [1, 2, 3, 4, 5, 6])

    def test_v5o_s_an_orphan_run_is_no_row_and_needs_nobody(self):
        # A run going under a seat that was simply stopped is no row and no
        # project: the menu at rest is the seats.
        screen, _ = self.draw(100, 30)
        self.assertNotIn("Orphan going fine", screen)
        self.assertNotIn("↳", screen)
        # The fixture's own needs are unchanged: no extra one appears.
        self.assertIn("your projects · 2 need you", screen)
        self.assertNotIn("3 need", screen)
        # The records still have it, going, under nobody's seat.
        found = list(menu.run_records())
        self.assertIn("orphan-going", [d.name for d, _ in found])

    def test_v5o_u_empty_menu_pages_once_and_m_k_are_harmless(self):
        # draw returns ints even with nothing to show, so the loop's page keys
        # stay a harmless "not a key" instead of a TypeError.
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(menu.draw(self.cfg, []), (0, 1))
        answers = iter(["m", "k", "q"])
        with patch.object(menu.orch, "listing", return_value=[]), \
                patch.object(menu.orch, "job_notices", return_value=[]), \
                patch.object(menu, "read", side_effect=lambda *_: next(answers)), \
                patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        self.assertIn("not a key: 'm'", out.getvalue())
        self.assertIn("not a key: 'k'", out.getvalue())

    def test_v5o_t_width_helpers_default_to_the_terminal(self):
        # layout_width, content_width, rule_line and key_line all advertise a
        # no-argument call; it reads the terminal instead of raising.
        self.assertGreaterEqual(terminal.layout_width(), 1)
        self.assertGreaterEqual(terminal.content_width(), 1)
        self.assertLessEqual(terminal.layout_width(), 120)
        self.assertLessEqual(terminal.content_width(), 100)
        self.assertTrue(terminal.rule_line().strip("─") == "")
        self.assertTrue(any("n new" in line for line in terminal.key_line("n new   x stop")))

    def test_v5o_v_columns_align_across_projects_and_no_line_trails_space(self):
        # No rendered line keeps trailing space, plain or coloured: cell pads
        # land outside the escapes and every row is rstripped.
        for width in (40, 100, 170):
            screen, _ = self.draw(width, 30)
            for line in screen.splitlines():
                self.assertEqual(line, line.rstrip(), repr(line))
        with patch.object(terminal, "colour_depth", return_value=24):
            screen, _ = self.draw(100, 30)
            for line in screen.splitlines():
                self.assertEqual(line, line.rstrip(), repr(line))
        # Seat columns are sized once per draw from every row on screen, so
        # the count column starts at the same column under every project --
        # wide and on the phone, where the name column is the capped
        # widths["name_narrow"]. Rows are found by global number: names can
        # be cut on narrow screens, and the needs-you line owns no seat.
        for width in (40, 100, 170):
            ordered, _, _, _ = menu.v5o_groups(self.cfg, self.seats)
            widths = menu.v5o_column_widths([seat for project in ordered
                                             for seat in project["seats"]], width)
            name_w = widths["name_narrow"] if width < 60 else widths["name"]
            orch_w = widths.get("orch", widths.get("worker", 0))
            count_at = 2 + widths["num"] + 2 + name_w + 2 + orch_w + 2
            screen, _ = self.draw(width, 30)
            by_number = {}
            for line in screen.splitlines():
                # a head row, never a continuation: those are indented four columns
                m = re.match(r"^ {2}(\d+) +\S", line)
                if m:
                    # First match wins: a head row precedes its continuation.
                    by_number.setdefault(m.group(1), line)
            rows = 0
            for project in ordered:
                for seat in project["seats"]:
                    row = by_number[seat["number"]]
                    self.assertTrue(row[count_at:].startswith(
                        terminal.state_text(seat["count"])), row)
                    rows += 1
            self.assertGreater(rows, 3)


if __name__ == "__main__":
    if sys.argv[1:] == ["--fixtures"]:
        test = V5oMenu()
        test.setUp()
        try:
            for width, height in ((40, 30), (100, 30), (170, 30)):
                (REPO / f"tests/fixtures/v5o-{width}.txt").write_text(test.draw(width, height)[0])
        finally:
            test.doCleanups()
    else:
        unittest.main(verbosity=2)

