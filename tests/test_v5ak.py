"""v5ak: the menu at rest is the projects and their seats, nothing else; offline.

A fake ~/code with two checkouts, fake seats and fake run.json records, the real
renderer.  Nothing here touches a harness, a tmux server or the owner's own
~/.agentkit.  See docs/cli-design.md for the visual system.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import re
import shutil
from unittest.mock import patch
import unittest

from test_v4n import REPO, Sandbox
from agentkit import config, menu, orch, retention, run, terminal, watch

NOW = 1_800_000_000
DAY = 86400


class Projects(Sandbox):
    """Two checkouts under ~/code, seats in and beside them, runs of every shape."""

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=NOW))
        self.stack.enter_context(patch.object(menu.time, "strftime", return_value="14:02"))
        self.stack.enter_context(patch("agentkit.watch.live_state", side_effect=lambda seat, *a, **kw:
                                       {"state": seat.get("live", "at_prompt"), "rule": "fixture",
                                        "evidence": "",
                                        "began": seat.get("since", NOW - 600),
                                        "since": seat.get("since", NOW - 600)}))
        self.notices = {}
        self.stack.enter_context(patch.object(menu.notify, "last",
                                              side_effect=self.notices.get))
        # Two checkouts, one directory that is none, and one checkout nobody sits in.
        for name in ("atoll", "agentkit", "unstaffed"):
            (config.CODE / name / ".git").mkdir(parents=True)
        (config.CODE / "not-a-checkout").mkdir(parents=True)
        self.seats = []

    def seat(self, name, repo, live="at_prompt", since=NOW - 600):
        path = str(config.CODE / repo) if repo else str(self.root)
        session = {"name": name, "repo": path if repo else None, "path": path,
                   "live": live, "since": since, "created": NOW - 5 * DAY}
        config.save_session(self.cfg, name, "fable", ["opus"],
                            {"repo": path if repo else None, "cwd": path})
        self.seats.append(session)
        return session

    def record(self, name, owner, **extra):
        directory = config.RUNS / name
        directory.mkdir(exist_ok=True)
        state = {"run_id": name, "title": f"Finished {name}", "state": "pass",
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

    def draw(self, width=100, height=30, page=0, keys=menu.KEYS):
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=height), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, keys, page)
        return out.getvalue()

    @staticmethod
    def headings(screen):
        return [line for line in screen.splitlines()
                if line in ("atoll", "agentkit", "no project")]

    def test_v5ak_a_no_run_ever_makes_a_project_or_a_row(self):
        # Every repo a run can carry that is not a checkout under ~/code.
        self.seat("atoll-fix", "atoll")
        for name, repo in (("tmp-run", str(config.TMP / "smoke-repo")),
                           ("worktree-run", str(config.WT / "20260901-0101-old-work")),
                           ("workspace-run", str(config.WORK / "20260901-0101-old-work")),
                           ("outside-run", str(self.root / "elsewhere")),
                           ("run-id-run", str(config.RUNS / "20260901-0101-old-work")),
                           ("no-repo-run", None)):
            self.record(name, owner="gone-seat", repo=repo, title=f"Work in {name}",
                        state="fail", verdict="FAIL", finished_at=NOW - 2 * DAY)
            self.record(f"{name}-going", owner="stopped-seat", repo=repo,
                        title=f"Going in {name}", state="running", finished_at=None,
                        started_at=NOW - 600, rounds=2, round_summaries=[])
            self.assertIsNone(orch.checkout_of(repo), name)
        screen = self.draw(100, 30)
        self.assertEqual(self.headings(screen), ["atoll"])
        for name in ("tmp-run", "worktree-run", "workspace-run", "outside-run", "run-id-run",
                     "no-repo-run"):
            self.assertNotIn(f"Work in {name}", screen)
            self.assertNotIn(f"Going in {name}", screen)
        for word in ("↳", "scratch", "smoke-repo", "20260901-0101-old-work", "elsewhere"):
            self.assertNotIn(word, screen)
        # A checkout is the one a repo *is*, never one it merely sits under.
        self.assertEqual(orch.checkout_of(str(config.CODE / "atoll")), config.CODE / "atoll")
        self.assertIsNone(orch.checkout_of(str(config.CODE / "atoll" / "agentkit")))
        self.assertIsNone(orch.checkout_of(str(config.CODE / "not-a-checkout")))
        self.assertIsNone(orch.checkout_of(""))
        self.assertIsNone(orch.checkout_of(None))

    def test_v5ak_b_one_heading_per_checkout_and_a_fallback_for_the_rest(self):
        self.seat("atoll-fix", "atoll")
        self.seat("atoll-plan", "atoll")
        self.seat("herdr", None)                  # works across projects from ~/code
        self.seat("stray", "not-a-checkout")      # a directory under ~/code that is no checkout
        screen = self.draw(100, 30)
        self.assertEqual(self.headings(screen),
                         ["atoll", "no project"])
        # A project is never listed twice, and a checkout with no seat is not listed.
        self.assertEqual(screen.count("\natoll\n"), 1)
        self.assertNotIn("unstaffed", screen)
        self.assertNotIn("agentkit · ", screen)
        # `n` offers the checkouts; `not-a-checkout` is none of them, and so is no project.
        self.assertEqual([path.name for path in orch.checkouts()],
                         ["agentkit", "atoll", "unstaffed"])
        # Both seats of a checkout sit under its one heading.
        self.seats = [self.seats[0], self.seats[2]]
        screen = self.draw(100, 30)
        self.assertEqual(self.headings(screen), ["atoll", "no project"])

    def test_v5ak_b2_agentkit_s_own_checkout_is_a_project_beside_code(self):
        # agentkit lives at ~/agentkit, not under ~/code, and is a checkout all the same,
        # named by its directory; its worktrees are still none.
        shutil.rmtree(config.CODE / "agentkit")
        own = Path.home() / "agentkit"
        (own / ".git").mkdir(parents=True)
        self.assertEqual(orch.checkout_of(str(own)), own)
        self.assertIsNone(orch.checkout_of(str(config.WT / "20260901-0101-agentkit-work")))
        self.assertEqual([path.name for path in orch.checkouts()],
                         ["agentkit", "atoll", "unstaffed"])
        # Two seats in it share its one heading.
        self.seat("agentkit-updates", str(own))
        self.seat("ak-verification", str(own))
        screen = self.draw(100, 30)
        self.assertEqual(self.headings(screen), ["agentkit"])
        self.assertIn("agentkit-updates", screen)
        self.assertIn("ak-verification", screen)

    def test_v5ak_c_seats_only_never_a_run_row(self):
        seat = self.seat("atoll-fix", "atoll", live="working")
        self.record("going", owner=seat["name"], repo=seat["repo"], title="Going work",
                    state="running", finished_at=None, started_at=NOW - 600,
                    rounds=2, round_summaries=[], **run.process_owner())
        self.record("failed", owner=seat["name"], repo=seat["repo"], title="Failed work",
                    state="fail", verdict="FAIL", finished_at=NOW - 2 * DAY)
        self.record("parked", owner=seat["name"], repo=seat["repo"], title="Parked work",
                    state="exhausted", finished_at=None, started_at=NOW - 4 * 3600,
                    rounds=2, round_summaries=[])
        screen = self.draw(100, 30)
        self.assertNotIn("↳", screen)
        # A working seat without a plan or a job reads empty, never `N running`; no run
        # title ever is a row.
        for title in ("Failed work", "Parked work", "Going work"):
            self.assertNotIn(title, screen)
        row = next(line for line in screen.splitlines() if "atoll-fix" in line)
        self.assertTrue(row.rstrip().endswith("● working"))   # the parked one resumes itself
        self.assertEqual(self.headings(screen), ["atoll"])
        # Its own runs are still going, so the seat is working and needs nobody yet.
        self.assertIn("your projects · nothing needs you", screen)
        self.assertEqual(menu.v5o_groups(self.cfg, self.seats)[2], 0)
        # The records stay for `ak run status`, which is where runs are looked up.
        self.assertEqual({d.name for d, _ in menu.run_records()},
                         {"going", "parked", "failed"})

    def test_v5ak_d_the_count_is_said_once_on_the_top_line(self):
        self.seat("atoll-fix", "atoll")
        self.notices["atoll-fix"] = {"kind": "needs", "text": "Which schema?",
                                     "time": NOW - 300}
        self.seat("atoll-plan", "atoll", live="draft")
        self.seat("herdr", "agentkit", since=NOW - DAY)
        count = re.compile(r"nothing needs you|\d+ needs? you|\d+ need you")

        def counted(screen):
            return [line for line in screen.splitlines() if count.search(line)]

        screen = self.draw(100, 30)
        self.assertEqual(counted(screen), ["your projects · 3 need you"])
        # No heading ever says it, however many of its seats need him.
        for line in self.headings(screen):
            self.assertNotIn("needs you", line)
            self.assertNotIn("need you", line)
        # A seat's own state word is its state, said once on each needing row.
        self.assertEqual(screen.count("! needs you"), 3)
        # One needing seat, and none at all: still once, still the top line.
        self.seats = self.seats[:1]
        self.assertEqual(counted(self.draw(100, 30)), ["your projects · 1 needs you"])
        self.seats[0]["live"] = "working"
        self.notices.clear()
        self.assertEqual(counted(self.draw(100, 30)),
                         ["your projects · nothing needs you"])
        # And at every width, including the phone's compact frame: no line but the
        # heading ever says it, and on the narrowest screens the heading is cut
        # rather than repeated -- the page is the one part that is never cut.
        self.seats[0]["live"] = "at_prompt"
        for width, height in ((40, 30), (40, 12), (170, 30), (100, 10), (30, 8)):
            screen = self.draw(width, height)
            said = [line for line in screen.splitlines()
                    if re.search(r"\d+ needs? you|nothing needs you", line)]
            self.assertLessEqual(len(said), 1, screen)
            for line in said:
                self.assertTrue(line.lstrip().startswith("your projects"), line)
            head = next(line for line in screen.splitlines() if "your projects" in line)
            self.assertTrue(head.lstrip().startswith("your projects"), head)

    def test_v5ak_e_no_ending_ever_needs_him(self):
        # An ended run is its orchestrator's business, fresh or eight days old: a gone
        # seat names its own number, and no row ever says `press r`.
        seat = self.seat("atoll-fix", "atoll")
        seat["exited"] = True
        failed = self.record("failed", owner=seat["name"], repo=seat["repo"],
                             title="Failed work", state="fail", verdict="FAIL",
                             finished_at=NOW - 2 * DAY)
        self.assertRegex(self.draw(100, 30), re.compile(
            r"atoll-fix\s+fable\s+! needs you\s+session closed: press 1 to reopen$", re.M))
        state = run.read_state(failed)
        state["finished_at"] = NOW - 8 * DAY
        run.save_state(failed, state)
        self.assertRegex(self.draw(100, 30), re.compile(
            r"atoll-fix\s+fable\s+! needs you\s+session closed: press 1 to reopen$", re.M))
        self.record("stopped", owner=seat["name"], repo=seat["repo"], title="Stopped work",
                    state="interrupted", finished_at=None, started_at=NOW - 2 * DAY,
                    interrupted_at=NOW - 2 * DAY, recovery_pending=True)
        self.assertNotIn("press r", self.draw(100, 30))
        self.record("unmerged", owner=seat["name"], repo=seat["repo"], title="Unmerged pass",
                    state="pass", verdict="PASS", finished_at=NOW - 2 * DAY)
        screen = self.draw(100, 30)
        self.assertIn("session closed: press 1 to reopen", screen)
        self.assertNotIn("press r", screen)

    def test_v5ak_f_a_parked_run_is_the_loops_and_stays_working(self):
        seat = self.seat("atoll-fix", "atoll")
        for name, word in (("parked", "exhausted"), ("stuck-run", "stalled")):
            self.record(name, owner=seat["name"], repo=seat["repo"], title=f"{word} work",
                        state=word, error="provider quota spent", finished_at=None,
                        started_at=NOW - 4 * 3600, rounds=2, round_summaries=[],
                        quota_dry=word == "exhausted")
        screen = self.draw(100, 30)
        self.assertIn("nothing needs you", screen)
        self.assertNotIn("press", screen.split("n new")[0])
        for name in ("parked", "stuck-run"):
            state = run.read_state(config.RUNS / name)
            self.assertFalse(menu.v5o_needs_look(state, now=NOW), name)
            self.assertEqual(menu.runs_word(state), "working")
        # ak run status reads the same word from the same table.
        self.assertEqual(menu.run_state_word(run.read_state(config.RUNS / "parked")),
                         "working")

    def test_v5ak_g_the_tally_counts_endings_the_row_never_names(self):
        seat = self.seat("atoll-fix", "atoll")
        seat["exited"] = True
        self.record("fresh-fail", owner=seat["name"], repo=seat["repo"], state="fail",
                    verdict="FAIL", finished_at=NOW - 2 * DAY)
        self.record("old-fail", owner=seat["name"], repo=seat["repo"], state="fail",
                    verdict="FAIL", finished_at=NOW - 8 * DAY)
        self.record("parked", owner=seat["name"], repo=seat["repo"], state="exhausted",
                    finished_at=None, started_at=NOW - 4 * 3600, quota_dry=True)
        self.record("acknowledged", owner=seat["name"], repo=seat["repo"], state="error",
                    finished_at=NOW - DAY, recovery_acknowledged_at=NOW - 3600)
        self.record("unmerged", owner=seat["name"], repo=seat["repo"], state="pass",
                    verdict="PASS", finished_at=NOW - DAY)
        records = list(menu.run_records())
        states = [state for _, state in records]
        rows = sum(1 for state in states
                   if menu.v5o_needs_look(state, states, None, NOW)
                   and run.launched_session(state) == seat["name"])
        tallies = run.seat_tallies(states, now=NOW)
        self.assertEqual(rows, 2)                      # fresh-fail and unmerged
        self.assertEqual(tallies[seat["name"]][1], rows)
        # the parked run is going, and counts as going in the tally
        self.assertEqual(menu.tally(tallies[seat["name"]]), "1 running · 2 needs you")
        # Its parked run resumes itself, so the seat is working until that one ends;
        # then the gone seat names its own number, never the endings.
        self.assertIn("● working", self.draw(100, 30))
        run.save_state(config.RUNS / "parked",
                       {**run.read_state(config.RUNS / "parked"), "state": "pass",
                        "merged": True, "finished_at": NOW - 60})
        screen = self.draw(100, 30)
        self.assertIn("session closed: press 1 to reopen", screen)
        self.assertNotIn("press r", screen)

    def test_v5ak_h_the_three_fixtures_reproduce_byte_for_byte(self):
        import test_v5o
        for width in (40, 100, 170):
            fixture = test_v5o.V5oMenu()
            fixture.setUp()
            try:
                screen = fixture.draw(width, 30)[0]
            finally:
                fixture.doCleanups()
            self.assertEqual(screen, (REPO / f"tests/fixtures/v5o-{width}.txt").read_text())
            self.assertNotIn("↳", screen)
            # once on the top line, and once in each needing seat's own state column
            self.assertLessEqual(len(re.findall(r"need you|needs you", screen)), 4)

    def test_v5ak_i_gc_collects_throwaway_runs_and_keeps_everything_else(self):
        # The checkout run's seat is still there: a month-old run of a seat that is gone
        # goes whole, throwaway or not (test_cleanup's 31-day run).
        self.seat("atoll-fix", "atoll")
        old = self.record("old-throwaway", owner="smoke-seat",
                          repo=str(config.TMP / "smoke-repo"), state="fail",
                          finished_at=NOW - 8 * DAY, started_at=NOW - 8 * DAY - 1800)
        young = self.record("young-throwaway", owner="smoke-seat",
                            repo=str(config.TMP / "smoke-repo"), state="fail",
                            finished_at=NOW - DAY, started_at=NOW - DAY - 1800)
        kept = self.record("checkout-run", owner="atoll-fix",
                           repo=str(config.CODE / "atoll"), state="fail",
                           finished_at=NOW - 30 * DAY, started_at=NOW - 30 * DAY - 1800)
        live = self.record("live-throwaway", owner="smoke-seat",
                           repo=str(config.TMP / "smoke-repo"), state="running",
                           finished_at=None, started_at=NOW - 8 * DAY,
                           **run.process_owner())
        self.assertTrue(retention.throwaway(str(config.TMP / "smoke-repo")))
        self.assertTrue(retention.throwaway(str(config.TMP)))
        self.assertFalse(retention.throwaway(str(config.CODE / "atoll")))
        self.assertFalse(retention.throwaway(None))
        plan = run.gc_plan(now=NOW)
        self.assertEqual([item["path"] for item in plan if item["kind"] == "throwaway-run"],
                         [str(old)])
        removed = run.gc(lambda _: None)
        self.assertEqual(removed, [str(old)])
        self.assertFalse(old.exists())
        # A younger one, a run under a checkout and a live one all stay put.
        for directory in (young, kept, live):
            self.assertTrue(directory.exists(), directory)
        self.assertEqual(run.gc(lambda _: None), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
