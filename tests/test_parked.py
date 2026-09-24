"""Every parked run has a scheduled resume, and status says when.

Entirely offline. The usage providers are fake dicts, the resume is a fake hook on
run.spawn_bg (one resume drives `cmd_resume` with the drive itself stubbed), the
upstream sha is a stubbed run.upstream_sha (no fetch ever leaves the box), and no
real adapter, model call or worker process is made anywhere in here. The stop hook
runs against the same throwaway state as the tick.
"""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, run, watch

WEEK = 604800
TRANSPORT_DEATH = ("reviewer spark died on API/transport errors 3 times and no eligible "
                   "reviewer is left to review; waiting for review. See out*/stderr.log")
NO_VERDICT = ("reviewer spark gave no verdict twice and no eligible reviewer is left "
              "to review; waiting for review")
# Legacy conflict FAILs remain eligible for parking only with task rounds left.
CONFLICT_NOTE = "the fixer did not finish the rebase of origin/main; it was aborted"
BUDGET_NOTE = "the rebase of origin/main conflicted and the round budget (3) is spent"

TASK = ("# Fix the parser\n\n## Done when\n\n```bash\ntest -f deliverable\n```\n")


def meter(name, used, resets_at, window=WEEK):
    return {"name": name, "used": used, "resets_at": resets_at, "window_secs": window,
            "pace": None}


class Parked(unittest.TestCase):
    """One patched home, the shipped default config, fake providers, fake resumes."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".run-parked-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(self.root), "PYTHONDONTWRITEBYTECODE": "1",
            "AK_RUN_ROLE": "orchestrator"}))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()
        self.cfg = config.load()
        config.save_session(self.cfg, "seat", "fable", ["opus", "astra", "spark"])
        self.now = time.time()
        self.logs = []
        self.log = self.logs.append

    def providers(self, openai_used=10, anthropic_used=100, meta_used=100):
        """Fake usage providers: openai refilled, the rest dry, unless told otherwise."""
        return {
            "anthropic": {"meters": [meter("weekly_all", anthropic_used, self.now + WEEK),
                                     meter("weekly_scoped", anthropic_used, self.now + WEEK)]},
            "openai": {"meters": [meter("weekly", openai_used, self.now + WEEK)]},
            "meta": {"meters": [meter("weekly", meta_used, self.now + WEEK)]},
        }

    def receipt(self, name, state="error", worktree=True, task=True, **extra):
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        wt = self.root / f"wt-{name}"
        if worktree:
            wt.mkdir(parents=True)
        if task:
            (run_dir / "task.md").write_text(TASK)
        base = {"run_id": name, "title": f"Parked run ({name})", "state": state,
                "verdict": None, "executor": "astra", "reviewer": "spark",
                "rounds": 3, "round_summaries": [],
                "launched_session": "seat" if state in ("error", "fail", "waiting") else None,
                "repo": str(self.root), "worktree": str(wt),
                "branch": "run-x", "base": "main", "base_sha": "0" * 40,
                "error": "executor astra died on API/transport errors 3 times in round 1",
                "started_at": self.now - 600, "finished_at": self.now - 60}
        base.update(extra)
        run.save_state(run_dir, base)
        return run_dir

    def test_parked_error_is_born_scheduled_and_retried_when_due(self):
        run_dir = self.receipt("20260922-1200-err")
        run.mark_state(run_dir, "error", "executor astra died on API/transport errors")
        state = run.read_state(run_dir)
        # the first rung is the loop's own: a minute out, rung zero, working already
        self.assertEqual(state["error_retries"], 0)
        self.assertAlmostEqual(state["error_retry_at"], state["finished_at"] + 60, delta=5)
        self.assertTrue(run.going(state))
        self.assertEqual(menu.run_state_word(state), "working")
        calls = []
        with patch.object(run, "spawn_bg", side_effect=lambda d, a, expected=None:
                          calls.append((d, a, expected)) or 0):
            watch.resume_errored(log=self.log, now=self.now + 61)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], ["resume", run_dir.name])
        self.assertIn(f"resumed {run_dir.name}: error retry 1", self.logs)
        state = run.read_state(run_dir)
        # the rung climbed before the child owned the run: the next retry waits 300 s
        self.assertEqual(state["error_retries"], 1)
        self.assertEqual(state["error_retry_at"], self.now + 61 + 300)

    def test_parked_error_retry_climbs_the_ladder_then_holds_hourly(self):
        self.assertEqual([run.error_retry_delay(n) for n in (0, 1, 2, 3, 4, 5, 99)],
                         [60, 300, 900, 1800, 3600, 3600, 3600])
        run_dir = self.receipt("20260922-1201-ladder", error_retry_at=self.now + 300,
                               error_retries=1)
        with patch.object(run, "spawn_bg",
                          side_effect=AssertionError("the ladder has not run out yet")):
            watch.resume_errored(log=self.log, now=self.now)
        self.assertEqual(self.logs, [])
        with patch.object(run, "spawn_bg", return_value=0):
            watch.resume_errored(log=self.log, now=self.now + 300)
        state = run.read_state(run_dir)
        self.assertEqual((state["error_retries"], state["error_retry_at"]),
                         (2, self.now + 300 + 900))

    def test_parked_failed_error_resume_stays_error_and_keeps_its_rung(self):
        # the real spawn_bg, which parks a failed launch as interrupted: the tick must
        # put the run back to error, stay silent, and fire again on the ladder's hour.
        from types import SimpleNamespace
        run_dir = self.receipt("20260922-1202-retry", error_retry_at=self.now - 1,
                               error_retries=2)
        launches = []

        def fork(*args, **kwargs):
            launches.append(args)
            if len(launches) == 1:
                raise OSError("fixture cannot fork")
            return SimpleNamespace(pid=99999999)

        with patch.object(run.subprocess, "Popen", side_effect=fork), \
                patch("agentkit.orch.find", return_value=None):
            watch.resume_errored(log=self.log, now=self.now)
            self.assertEqual(len(launches), 1)
            self.assertTrue(any("WARN could not resume" in line for line in self.logs),
                            self.logs)
            state = run.read_state(run_dir)
            self.assertEqual(state["state"], "error")
            self.assertNotIn("recovery_pending", state)
            # the rung this launch consumed stays consumed: the next retry is half
            # an hour out, and the tick stays quiet until then
            self.assertEqual((state["error_retries"], state["error_retry_at"]),
                             (3, self.now + 1800))
            watch.resume_errored(log=self.log, now=self.now)
            self.assertEqual(len(launches), 1)    # throttled inside the rung
            watch.resume_errored(log=self.log, now=self.now + 3600)
            self.assertEqual(len(launches), 2)    # retried once the ladder allows
            state = run.read_state(run_dir)
            self.assertEqual((state["state"], state["resume_from"]), ("queued", "error"))

    def test_parked_unresumable_error_keeps_no_schedule(self):
        # a task that never parsed can never resume: stamping it would only fail on
        # the hour, every hour, saying nothing new. It parks for a person instead.
        run_dir = self.receipt("20260922-1203-taskbug")
        (run_dir / "task.md").write_text("# No done when here\n")
        run.mark_state(run_dir, "error", "task.md: no `## Done when` section")
        state = run.read_state(run_dir)
        self.assertNotIn("error_retry_at", state)
        self.assertNotIn("error_retries", state)
        self.assertFalse(run.going(state))
        self.assertEqual(menu.run_state_word(state), "needs you")
        with patch.object(run, "spawn_bg",
                          side_effect=AssertionError("nobody can run this task")):
            watch.resume_errored(log=self.log, now=self.now)
        self.assertEqual(self.logs, [])
        # ... and a worktree that went missing after the stamp loses it, once, loudly
        run_dir = self.receipt("20260922-1204-gone", worktree=False,
                               error_retry_at=self.now - 1, error_retries=0)
        run.save_state(run_dir, {**run.read_state(run_dir),
                                 "worktree": str(self.root / "nowhere")})
        with patch.object(run, "spawn_bg",
                          side_effect=AssertionError("no resume without a worktree")):
            watch.resume_errored(log=self.log, now=self.now)
        state = run.read_state(run_dir)
        self.assertEqual(state["state"], "error")
        self.assertNotIn("error_retry_at", state)
        self.assertNotIn("error_retries", state)
        self.assertTrue(any("WARN" in line and "parked for a person" in line
                            for line in self.logs), self.logs)

    def test_parked_reviewer_transport_exhausted_resumes_when_reviewer_eligible(self):
        # opus executes, spark died reviewing, astra on openai is healthy and legal
        run_dir = self.receipt("20260922-1205-reviewer", state="exhausted",
                               executor="opus", error=TRANSPORT_DEATH)
        calls = []
        with patch.object(run, "spawn_bg", side_effect=lambda d, a, expected=None:
                          calls.append((d, a, expected)) or 0):
            watch.resume_exhausted(self.cfg, self.providers(), log=self.log, now=self.now)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], ["resume", run_dir.name])
        state = run.read_state(run_dir)
        # the executor never died, so it stays: the resume re-picks the reviewer
        self.assertEqual(state["executor"], "opus")
        self.assertNotIn("executor_history", state)
        self.assertTrue(any(line.startswith(f"resumed {run_dir.name}: reviewer ")
                            and line.endswith("eligible again") for line in self.logs),
                        self.logs)
        # ... but with every reviewer dry the run keeps waiting, silently
        run_dir = self.receipt("20260922-1206-noreviewer", state="exhausted",
                               executor="opus", error=TRANSPORT_DEATH)
        dry = self.providers(openai_used=100, anthropic_used=100, meta_used=100)
        self.logs.clear()
        with patch.object(run, "spawn_bg",
                          side_effect=AssertionError("no reviewer is eligible")):
            watch.resume_exhausted(self.cfg, dry, log=self.log, now=self.now)
        self.assertEqual(self.logs, [])
        self.assertEqual(run.read_state(run_dir)["state"], "exhausted")

    def test_parked_transport_resume_uses_the_runs_worker_list(self):
        run_dir = self.receipt("20260923-0400-bound-reviewer", state="exhausted",
                               executor="opus", error=TRANSPORT_DEATH,
                               workers=["opus", "spark"])
        # The tick's own selection has a healthy reviewer, but this run never
        # selected it. Only a reviewer from the saved list can end the wait.
        with patch.object(run, "spawn_bg", return_value=0) as spawn:
            watch.resume_exhausted(self.cfg, self.providers(), workers=["astra"],
                                   log=self.log, now=self.now)
            spawn.assert_not_called()
            self.assertEqual(self.logs, [])
            self.assertNotIn("exhausted_resume_at", run.read_state(run_dir))
            watch.resume_exhausted(self.cfg, self.providers(meta_used=10), workers=["astra"],
                                   log=self.log, now=self.now)
        spawn.assert_called_once()
        self.assertEqual(spawn.call_args.args, (run_dir, ["resume", run_dir.name]))
        self.assertEqual(run.read_state(run_dir)["executor"], "opus")
        self.assertIn(f"resumed {run_dir.name}: reviewer spark eligible again", self.logs)

    def test_parked_waiting_retries_after_main_moves(self):
        old, new = "0" * 40, "1" * 40
        run_dir = self.receipt("20260922-1207-wait", state="waiting", verdict="FAIL",
                               error=CONFLICT_NOTE, merge_note=CONFLICT_NOTE,
                               round_summaries=[{"round": 1, "verdict": "PASS",
                                                 "done_when": True}],
                               waiting_on={"ref": "origin/main", "sha": old})
        (run_dir / "log.txt").write_text(f"not merged: {CONFLICT_NOTE}\n")
        calls = []
        with patch.object(run, "upstream_sha", return_value=old), \
                patch.object(run, "spawn_bg",
                             side_effect=AssertionError("main has not moved")):
            watch.resume_waiting(log=self.log, now=self.now)
        self.assertEqual(self.logs, [])
        self.assertEqual(run.read_state(run_dir)["state"], "waiting")
        with patch.object(run, "upstream_sha", return_value=new), \
                patch.object(run, "spawn_bg", side_effect=lambda d, a, expected=None:
                             calls.append((d, a, expected)) or 0):
            watch.resume_waiting(log=self.log, now=self.now)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], ["resume", run_dir.name])
        self.assertIn(f"resumed {run_dir.name}: origin/main moved ({old[:12]}..{new[:12]})",
                      self.logs)
        # the fake resume changes nothing on disk; later phases must not see it again
        run.save_state(run_dir, {**run.read_state(run_dir), "state": "queued"})
        # the park itself: a conflict FAIL with rounds left waits on its upstream
        failed = self.receipt("20260922-1208-conflict", state="fail", verdict="FAIL",
                              error=None, merge_note=CONFLICT_NOTE,
                              round_summaries=[{"round": 1, "verdict": "PASS",
                                                "done_when": True}])
        (failed / "log.txt").write_text(f"not merged: {CONFLICT_NOTE}\n")
        self.logs.clear()
        with patch.object(run, "upstream_sha", return_value=new), \
                patch.object(run, "spawn_bg",
                             side_effect=AssertionError("parking launches nothing")):
            watch.resume_waiting(log=self.log, now=self.now)
        state = run.read_state(failed)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(state["waiting_on"], {"ref": "origin/main", "sha": new})
        self.assertIn(f"parked {failed.name} waiting on origin/main at {new[:12]}",
                      self.logs)
        run.save_state(failed, {**state, "state": "queued"})
        # ... while a conflict FAIL at its budget stays a FAIL for its owner
        spent = self.receipt("20260922-1209-spent", state="fail", verdict="FAIL",
                             error=None, merge_note=BUDGET_NOTE,
                             round_summaries=[{"round": n} for n in (1, 2, 3)])
        (spent / "log.txt").write_text(f"not merged: {BUDGET_NOTE}\n")
        with patch.object(run, "upstream_sha",
                          side_effect=AssertionError("at budget: never parked")), \
                patch.object(run, "spawn_bg",
                             side_effect=AssertionError("at budget: never resumed")):
            watch.resume_waiting(log=self.log, now=self.now)
        self.assertEqual(run.read_state(spent)["state"], "fail")

    def test_parked_merge_wait_resumes_with_task_rounds_spent(self):
        old, new = "0" * 40, "1" * 40
        identity = {"head_sha": "2" * 40, "tree_sha": "3" * 40}
        for name, reason, verdict in (
                ("conflict", CONFLICT_NOTE, None),
                ("race", "the base moved under 3 merge attempts", "PASS"),
                # a once suite failing on the account after every review passed
                ("final", "the final check still fails after 3 fixer rounds: "
                          "`bash tests/smoke.sh` — FAIL 4 no delete_repo scope", "PASS")):
            with self.subTest(reason=reason):
                run_dir = self.receipt(f"20260923-1400-merge-{name}", state="running",
                                       verdict=verdict, launched_session="seat",
                                       round_summaries=[{"round": n, "verdict": "PASS",
                                                         "done_when": True, **identity}
                                                        for n in (1, 2, 3)])
                lp = SimpleNamespace(state=run.read_state(run_dir), run_dir=run_dir,
                                     log=run.note_in(run_dir / "log.txt"))
                run.park_waiting(lp, reason, "origin/main", old)
                # the retry is scheduled, and status says when
                with redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(run.cmd_status([run_dir.name]), 0)
                self.assertIn("waiting · retry after the next merge to origin/main",
                              out.getvalue())
                with patch.object(run, "upstream_sha", return_value=old), \
                        patch.object(run, "spawn_bg", return_value=0) as spawn:
                    watch.resume_waiting(log=self.log, now=self.now)
                    spawn.assert_not_called()
                with patch.object(run, "upstream_sha", return_value=new), \
                        patch.object(run, "spawn_bg", return_value=0) as spawn:
                    watch.resume_waiting(log=self.log, now=self.now)
                    spawn.assert_called_once()
                    self.assertEqual(spawn.call_args.args,
                                     (run_dir, ["resume", run_dir.name]))
                waiting = run.read_state(run_dir)
                self.assertEqual(waiting["state"], "waiting")
                self.assertNotIn("--rounds", run.continue_line(waiting, run_dir))
                with patch.object(run, "commit_identity", return_value=identity), \
                        patch.object(run, "drive", return_value=0):
                    self.assertEqual(run.cmd_resume([run_dir.name]), 0)
                after = run.read_state(run_dir)
                self.assertEqual(after["state"], "queued")
                self.assertEqual(after["resume_from"], "waiting")
                self.assertEqual(after["rounds"], 3)
                self.assertEqual(after["round_summaries"], waiting["round_summaries"])
                self.assertTrue(run.review_pass(after, self.cfg))
                self.assertNotIn("waiting_on", after)

    def test_parked_status_shows_the_retry_time(self):
        at = self.now + 3700
        run_dir = self.receipt("20260922-1210-when", error_retry_at=at, error_retries=0)
        want = f"error · retry {time.strftime('%H:%M', time.localtime(at))}"
        admission = ("session seat exists; ending under 24h old; "
                     "not handed back, carded or acknowledged")
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.cmd_status([]), 0)
        self.assertIn(f"{want} · {admission}", out.getvalue())
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.cmd_status([run_dir.name]), 0)
        self.assertIn(f"{want} · {admission}", out.getvalue())
        self.assertFalse(run.read_state(run_dir).get("recovery_acknowledged_at"))
        with patch.object(run, "spawn_bg", return_value=0) as spawn:
            watch.resume_errored(log=self.log, now=at)
        spawn.assert_called_once()
        want = "error · retry " + time.strftime('%H:%M', time.localtime(at + 300))
        waiter = self.receipt("20260922-1211-main", state="waiting", verdict="FAIL",
                              error=CONFLICT_NOTE, merge_note=CONFLICT_NOTE,
                              waiting_on={"ref": "origin/main", "sha": "0" * 40})
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.cmd_status([waiter.name]), 0)
        self.assertIn("waiting · retry after the next merge to origin/main", out.getvalue())
        self.assertIn(admission, out.getvalue())
        reviewer = self.receipt("20260922-1212-review", state="exhausted",
                                error=TRANSPORT_DEATH)
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.cmd_status([reviewer.name]), 0)
        self.assertIn("exhausted · resumes when a reviewer is eligible", out.getvalue())
        # ... and the default listing carries the same dim lines under each row
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.cmd_status([]), 0)
        table = out.getvalue()
        self.assertIn(want, table)
        self.assertIn("waiting · retry after the next merge to origin/main", table)
        self.assertIn(admission, table)
        self.assertIn("exhausted · resumes when a reviewer is eligible", table)

    def test_parked_run_without_schedule_reads_needs_you(self):
        run_dir = self.receipt("20260922-1213-parked", worktree=False,
                               error="task.md: no `## Done when` section")
        (run_dir / "task.md").unlink()
        run.mark_state(run_dir, "error", "task.md: no `## Done when` section")
        state = run.read_state(run_dir)
        self.assertNotIn("error_retry_at", state)
        want = f"run {run_dir.name} parked: task.md: no `## Done when` section"
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.cmd_status([run_dir.name]), 0)
        screen = out.getvalue()
        self.assertIn("needs you", screen)
        self.assertIn(want, screen)
        # ... and so does the seat that launched it: the word is needs you, the
        # reason names the run, because nobody else will take it up
        config.save_session(self.cfg, "seat", "astra", ["astra", "spark"])
        run.save_state(run_dir, {**state, "launched_session": "seat"})
        found = watch.session_state("seat", session={"name": "seat"}, cfg=self.cfg,
                                    records=[(run_dir, run.read_state(run_dir))],
                                    live={})
        self.assertEqual(found["word"], "needs you")
        self.assertEqual(found["reason"], want)

    def test_parked_settled_errors_do_not_override_the_seat(self):
        directory = self.receipt("20260923-0300-old-error", worktree=False,
                                  launched_session="seat")
        original = run.read_state(directory)
        # Each guard stands alone: an acknowledged or handed-back error need not
        # age out before a current turn or a later done can speak for its seat.
        for reason, extra in (
                ("aged", {"finished_at": self.now - run.GC_AGE - 1}),
                ("acknowledged", {"finished_at": self.now - 2 * 86400,
                                  "recovery_acknowledged_at": self.now - 60}),
                ("handed back", {"handed_back": self.now - 30}),
                ("hand-back pending", {"handback_pending": True}),
                ("superseded", {})):
            records = [(directory, {**original, **extra})]
            if reason == "superseded":
                # A replacement may have been delivered from another seat.
                records.append((config.RUNS / "replacement", {
                    "run_id": "replacement", "title": original["title"],
                    "state": "pass", "merged": True, "finished_at": self.now - 10,
                    "launched_session": "another-seat"}))
            for index in (None, run.supersession_index(records)):
                for word, detail, live, notice in (
                        ("working", "", {"hooked": "working",
                                          "hooked_at": self.now - 20}, None),
                        ("done", "Shipped it", {},
                         {"kind": "done", "text": "Shipped it", "time": self.now}),
                        ("needs you", "waiting for you", {}, None)):
                    with self.subTest(reason=reason, indexed=index is not None, word=word), \
                            patch.object(watch.notify, "last", return_value=notice):
                        found = watch.session_state(
                            "seat", self.now, session={"name": "seat"}, cfg=self.cfg,
                            records=records, index=index, live=live, harness="claude",
                            auth_out={}, gh_out={}, token_out={}, previous={})
                        self.assertEqual((found["word"], found["reason"]), (word, detail))

    def test_parked_conflict_upstream_names_a_ref_that_can_move(self):
        # the fixer note ends "... of origin/main; it was aborted": the capture must
        # stop at the `;`, or the run parks on a ref that can never move
        self.assertEqual(run.conflict_upstream({"merge_note": CONFLICT_NOTE}), "origin/main")
        self.assertEqual(run.conflict_upstream({"merge_note": BUDGET_NOTE}), "origin/main")
        self.assertEqual(run.conflict_upstream({"merge_note": None, "base": "main"}),
                         "origin/main")

    def test_parked_upstream_sha_accepts_only_a_full_sha(self):
        sha = "ab" * 20
        with patch.object(run, "git_out", return_value=(1, "fatal: no such repo")), \
                patch.object(run, "git", side_effect=AssertionError("no fetch, no rev")):
            self.assertIsNone(run.upstream_sha("/nowhere", "origin/main"))
        with patch.object(run, "git_out", return_value=(0, "")), \
                patch.object(run, "git", return_value="origin/main;^{commit}"):
            # what `rev-parse` echoes for a ref it cannot resolve: not a move
            self.assertIsNone(run.upstream_sha("/nowhere", "origin/main;"))
        with patch.object(run, "git_out", return_value=(0, "")), \
                patch.object(run, "git", return_value=""):
            self.assertIsNone(run.upstream_sha("/nowhere", "origin/main"))
        with patch.object(run, "git_out", return_value=(0, "")), \
                patch.object(run, "git", return_value=sha) as rev:
            self.assertEqual(run.upstream_sha("/nowhere", "origin/main"), sha)
            rev.assert_called_once_with("/nowhere", "rev-parse", "origin/main^{commit}",
                                        check=False)
        with patch.object(run, "git_out", return_value=(0, "")), \
                patch.object(run, "git", return_value="ef" * 32):
            # a sha256 repository's 64-char oids count as an answer too
            self.assertEqual(run.upstream_sha("/nowhere", "origin/main"), "ef" * 32)

    def test_parked_dry_run_changes_nothing_on_disk(self):
        due = self.receipt("20260922-1300-due", error_retry_at=self.now - 1,
                           error_retries=1)
        fresh = self.receipt("20260922-1301-fresh")
        run.save_state(fresh, {**run.read_state(fresh), "error_retry_at": None})
        gone = self.receipt("20260922-1302-gone", worktree=False,
                            error_retry_at=self.now - 1, error_retries=0)
        run.save_state(gone, {**run.read_state(gone),
                              "worktree": str(self.root / "nowhere")})
        waiter = self.receipt("20260922-1303-waiter", state="waiting", verdict="FAIL",
                              error=CONFLICT_NOTE, merge_note=CONFLICT_NOTE,
                              waiting_on={"ref": "origin/main", "sha": "0" * 40})
        failed = self.receipt("20260922-1304-failed", state="fail", verdict="FAIL",
                              error=None, merge_note=CONFLICT_NOTE,
                              round_summaries=[{"round": 1, "verdict": "PASS",
                                                "done_when": True}])
        (failed / "log.txt").write_text(f"not merged: {CONFLICT_NOTE}\n")
        before = {d: (d / "run.json").read_bytes()
                  for d in (due, fresh, gone, waiter, failed)}
        with patch.object(run, "spawn_bg",
                          side_effect=AssertionError("a dry run launches nothing")), \
                patch.object(run, "upstream_sha",
                             side_effect=AssertionError("a dry run fetches nothing")):
            watch.resume_errored(dry_run=True, log=self.log, now=self.now)
            watch.resume_waiting(dry_run=True, log=self.log, now=self.now)
        for d, content in before.items():
            self.assertEqual((d / "run.json").read_bytes(), content, d.name)
        self.assertIn(f"would resume {due.name}: error retry due", self.logs)
        self.assertIn(f"would schedule {fresh.name}: error retry", self.logs)
        self.assertIn(f"would leave {gone.name} parked for a person: "
                      "cannot be resumed where it stopped", self.logs)
        self.assertIn(f"would resume {waiter.name} after the next merge to origin/main",
                      self.logs)
        self.assertIn(f"would park {failed.name} waiting on origin/main", self.logs)

    def test_parked_transport_reresume_waits_out_the_hour(self):
        run_dir = self.receipt("20260922-1305-capped", state="exhausted",
                               executor="opus", error=TRANSPORT_DEATH,
                               exhausted_resume_at=self.now - 700)
        calls = []
        with patch.object(run, "spawn_bg", side_effect=lambda d, a, expected=None:
                          calls.append((d, a, expected)) or 0):
            # past the quota throttle, inside the hour: a dead reviewer costs
            # reviewer turns by the hour, not by the tick
            watch.resume_exhausted(self.cfg, self.providers(), log=self.log, now=self.now)
            self.assertEqual(calls, [])
            watch.resume_exhausted(self.cfg, self.providers(), log=self.log,
                                   now=self.now + 3600)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], ["resume", run_dir.name])

    def test_parked_no_verdict_exhausted_is_not_tick_resumed(self):
        self.assertTrue(run.reviewer_transport_dead(TRANSPORT_DEATH))
        self.assertFalse(run.reviewer_transport_dead(NO_VERDICT))
        self.assertFalse(run.reviewer_transport_dead(None))
        run_dir = self.receipt("20260922-1306-stuck", state="exhausted",
                               executor="opus", error=NO_VERDICT)
        with patch.object(run, "spawn_bg",
                          side_effect=AssertionError("stuck is not dead")):
            watch.resume_exhausted(self.cfg, self.providers(), log=self.log, now=self.now)
        self.assertEqual(self.logs, [])
        self.assertEqual(run.read_state(run_dir)["state"], "exhausted")
        self.assertEqual(run.parked_line(run.read_state(run_dir), run_dir.name), "")

    def test_parked_scheduled_error_is_never_announced(self):
        owned = self.receipt("20260922-1307-quiet", error_retry_at=self.now + 300,
                             error_retries=1, launched_session="seat")
        state = run.read_state(owned)
        self.assertFalse(run.owes_ending(state))
        with patch.object(run, "hand_back",
                          side_effect=AssertionError("nothing to hand back")):
            run.announce(state, owned, self.log, self.cfg)
        # ... while an error with no scheduled retry still owes its telling
        bare = self.receipt("20260922-1308-told", worktree=False,
                            launched_session="seat")
        run.save_state(bare, {**run.read_state(bare),
                              "worktree": str(self.root / "nowhere")})
        self.assertTrue(run.owes_ending(run.read_state(bare)))

    def test_parked_old_conflict_fail_is_never_parked(self):
        old = self.receipt("20260922-1309-old", state="fail", verdict="FAIL",
                           error=None, merge_note=CONFLICT_NOTE,
                           round_summaries=[{"round": 1}],
                           finished_at=self.now - run.GC_AGE - 1)
        (old / "log.txt").write_text(f"not merged: {CONFLICT_NOTE}\n")
        with patch.object(run, "upstream_sha",
                          side_effect=AssertionError("never parked, never fetched")), \
                patch.object(run, "spawn_bg",
                             side_effect=AssertionError("never parked, never resumed")):
            watch.resume_waiting(log=self.log, now=self.now)
        self.assertEqual(run.read_state(old)["state"], "fail")

    def test_parked_looked_at_conflict_fail_is_not_parked(self):
        self.assert_conflict_left_alone(recovery_acknowledged_at=self.now - 10)

    def test_parked_handed_back_conflict_fail_is_not_parked(self):
        self.assert_conflict_left_alone(handed_back=self.now - 10, handback_pending=True,
                                        handback_wait_reason="mid-turn")

    def test_parked_by_hand_conflict_fail_is_not_parked(self):
        self.assert_conflict_left_alone(launched_session=None)

    def test_parked_day_old_conflict_fail_is_not_parked(self):
        for age in (86400, 86401):
            with self.subTest(age=age):
                self.assert_conflict_left_alone(finished_at=self.now - age)

    def test_parked_carded_or_orphaned_conflict_fail_is_not_parked(self):
        for extra in ({"recovery_notified": "discord"}, {"launched_session": "gone"}):
            with self.subTest(extra=extra):
                self.assert_conflict_left_alone(**extra)

    def assert_conflict_left_alone(self, **extra):
        name = f"20260923-1200-conflict-{len(list(config.RUNS.iterdir()))}"
        directory = self.receipt(name, state="fail", verdict="FAIL", error=None,
                                 merge_note=CONFLICT_NOTE,
                                 round_summaries=[{"round": 1}], **extra)
        (directory / "log.txt").write_text(f"not merged: {CONFLICT_NOTE}\n")
        before = (directory / "run.json").read_bytes()
        with patch.object(run, "upstream_sha",
                          side_effect=AssertionError("history: never fetched")), \
                patch.object(run, "spawn_bg",
                             side_effect=AssertionError("history: never resumed")):
            watch.resume_waiting(dry_run=True, log=self.log, now=self.now)
            watch.resume_waiting(log=self.log, now=self.now)
        self.assertEqual((directory / "run.json").read_bytes(), before)
        self.assertEqual(self.logs, [])

    def test_parked_error_retry_drops_stamps_on_settled_old_and_unowned_endings(self):
        # The gate applies before scheduling an old receipt as well as before
        # spending a retry already stamped by the loop. Only stale retry marks go.
        for n, extra in enumerate((
                {"handed_back": self.now - 30}, {"recovery_notified": "discord"},
                {"recovery_acknowledged_at": self.now - 30},
                {"launched_session": None}, {"launched_session": "gone"},
                {"finished_at": self.now - 86400},
                {"finished_at": self.now - 86401}, {"finished_at": None},
                {"handed_back": self.now - 30, "task": False})):
            for stamped in (False, True):
                with self.subTest(extra=extra, stamped=stamped):
                    directory = self.receipt(f"20260923-1201-error-{n}-{stamped}", **extra)
                    if stamped:
                        run.save_state(directory, {**run.read_state(directory),
                                                   "error_retry_at": self.now - 1,
                                                   "error_retries": 2})
                    before = (directory / "run.json").read_bytes()
                    original = run.read_state(directory)
                    self.assertFalse(run.going(original))
                    self.assertEqual(menu.run_state_word(original), "needs you")
                    self.assertIn(f"run {directory.name} parked:",
                                  run.parked_line(original, now=self.now))
                    self.assertNotIn("retry", run.parked_line(original, now=self.now))
                    self.logs.clear()
                    with patch.object(run, "spawn_bg",
                                      side_effect=AssertionError("history stays stopped")):
                        watch.resume_errored(dry_run=True, log=self.log, now=self.now)
                        self.assertEqual((directory / "run.json").read_bytes(), before)
                        watch.resume_errored(log=self.log, now=self.now)
                    for key in ("error_retry_at", "error_retries"):
                        original.pop(key, None)
                    self.assertEqual(run.read_state(directory), original)
                    self.assertEqual(len(self.logs), 2 if stamped else 0)
                    if stamped:
                        self.assertIn("parked for a person", self.logs[-1])
                        if extra.get("task") is False:
                            self.assertIn("cannot be resumed where it stopped", self.logs[-1])
                    self.logs.clear()
                    watch.resume_errored(log=self.log, now=self.now)
                    self.assertEqual(self.logs, [])

    def test_parked_unowned_or_settled_error_is_born_without_a_retry(self):
        for n, extra in enumerate((
                {"launched_session": None}, {"launched_session": "gone"},
                {"handed_back": self.now - 30}, {"recovery_notified": "discord"},
                {"recovery_acknowledged_at": self.now - 30})):
            with self.subTest(extra=extra):
                directory = self.receipt(f"20260923-1210-born-{n}",
                                         error_retry_at=self.now - 1, error_retries=2, **extra)
                run.mark_state(directory, "error", "transport failed")
                state = run.read_state(directory)
                self.assertNotIn("error_retry_at", state)
                self.assertNotIn("error_retries", state)
                self.assertFalse(run.going(state))
                self.assertEqual(menu.run_state_word(state), "needs you")
                self.assertEqual(run.parked_line(state),
                                 f"run {directory.name} parked: transport failed")

    def test_parked_explicit_acknowledgement_cancels_error_retry(self):
        directory = self.receipt("20260923-1211-ack", error_retry_at=self.now - 1,
                                 error_retries=2)
        run.acknowledge(directory)
        state = run.read_state(directory)
        self.assertTrue(state["recovery_acknowledged_at"])
        self.assertNotIn("error_retry_at", state)
        self.assertNotIn("error_retries", state)
        self.assertFalse(run.going(state))
        with patch.object(run, "spawn_bg",
                          side_effect=AssertionError("acknowledged: never resumed")):
            watch.resume_errored(log=self.log, now=self.now)
        self.assertEqual(self.logs, [])
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.cmd_status([directory.name]), 0)
        self.assertIn(f"run {directory.name} parked:", out.getvalue())
        self.assertNotIn("retry due", out.getvalue())

    def test_parked_ineligible_waiting_run_is_not_resumed(self):
        for n, extra in enumerate((
                {"handed_back": self.now - 30}, {"recovery_notified": "discord"},
                {"recovery_acknowledged_at": self.now - 30},
                {"launched_session": None}, {"launched_session": "gone"},
                {"finished_at": self.now - 86400}, {"finished_at": self.now - 86401})):
            with self.subTest(extra=extra):
                directory = self.receipt(f"20260923-1212-wait-{n}", state="waiting",
                                         error=CONFLICT_NOTE, merge_note=CONFLICT_NOTE,
                                         waiting_on={"ref": "origin/main", "sha": "0" * 40},
                                         **extra)
                before = (directory / "run.json").read_bytes()
                with patch.object(run, "upstream_sha",
                                  side_effect=AssertionError("history: never fetched")), \
                        patch.object(run, "spawn_bg",
                                     side_effect=AssertionError("history: never resumed")):
                    watch.resume_waiting(dry_run=True, log=self.log, now=self.now)
                    watch.resume_waiting(log=self.log, now=self.now)
                self.assertEqual((directory / "run.json").read_bytes(), before)
                self.assertEqual(self.logs, [])
                state = run.read_state(directory)
                self.assertFalse(run.going(state))
                self.assertEqual(menu.run_state_word(state), "done")
                self.assertFalse(menu.v5o_needs_look(state, now=self.now))
                self.assertEqual(run.parked_line(state, now=self.now),
                                 f"run {directory.name} parked: {CONFLICT_NOTE}")

    def test_parked_ineligible_merge_wait_does_not_override_the_seat_or_page(self):
        directory = self.receipt("20260923-1215-history", state="waiting",
                                 error=CONFLICT_NOTE, merge_note=CONFLICT_NOTE,
                                 waiting_on={"ref": "origin/main", "sha": "0" * 40})
        original = run.read_state(directory)
        for extra in ({"finished_at": self.now - 25 * 3600},
                      {"handed_back": self.now - 30}, {"recovery_notified": "discord"},
                      {"recovery_acknowledged_at": self.now - 30},
                      {"launched_session": None}, {"launched_session": "gone"}):
            state = {**original, **extra}
            run.save_state(directory, state)
            records = [(directory, state)]
            for index in (None, run.supersession_index(records)):
                for word, live, notice in (
                        ("working", {"hooked": "working", "hooked_at": self.now - 20}, None),
                        ("done", {}, {"kind": "done", "text": "Shipped it", "time": self.now}),
                        ("needs you", {}, None)):
                    with self.subTest(extra=extra, indexed=index is not None, word=word), \
                            patch.object(watch.notify, "last", return_value=notice), \
                            patch.object(watch.notify, "_send_card", return_value=0) as send, \
                            patch.object(orch, "tmux_out", return_value=(0, "")):
                        facts = dict(session={"name": "seat"}, cfg=self.cfg, live=live,
                                     harness="claude", auth_out={}, gh_out={}, token_out={},
                                     previous={})
                        expected = watch.session_state("seat", self.now, records=[], **facts)
                        found = watch.session_state("seat", self.now, records=records,
                                                    index=index, **facts)
                        self.assertEqual(found, expected)
                        self.assertEqual(found["word"], word)
                        self.assertFalse(menu.v5o_needs_look(state, now=self.now))
                        self.assertTrue(all(counts == (0, 0, 0) for counts in
                                            run.seat_tallies([state], now=self.now).values()))
                        if word != "needs you":
                            for at in (self.now, self.now + 120):
                                self.assertEqual(watch.notify.transition(
                                    "seat", found, now=at, seat={"name": "seat"}), 0)
                            self.assertFalse(any(call.args[1] == "needs"
                                                 for call in send.call_args_list))
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(run.cmd_status([directory.name]), 0)
            self.assertIn(f"run {directory.name} parked: {CONFLICT_NOTE}", out.getvalue())
            self.assertNotIn("needs you", out.getvalue())

    def test_parked_stop_hook_waits_only_for_admitted_retries(self):
        # The real hook reads only this throwaway HOME; both record directories
        # point to the same fixtures the tick reads, never to the owner's state.
        home = self.root / "hook-home"
        ak = home / ".agentkit"
        ak.mkdir(parents=True)
        (ak / "runs").symlink_to(config.RUNS, target_is_directory=True)
        (ak / "state").symlink_to(config.STATE, target_is_directory=True)
        directory = self.receipt("20260923-1216-hook", error_retry_at=self.now + 60)
        original = run.read_state(directory)
        payload = json.dumps({"last_assistant_message": "I will carry on later."})
        for word in ("error", "waiting"):
            for extra in ({}, {"finished_at": self.now - 25 * 3600},
                          {"handed_back": self.now - 30}, {"recovery_notified": "discord"},
                          {"recovery_acknowledged_at": self.now - 30},
                          {"launched_session": None}, {"launched_session": "gone"}):
                with self.subTest(word=word, extra=extra):
                    state = {**original, "state": word, **extra}
                    run.save_state(directory, state)
                    # Even a run launched during this turn cannot justify a stop
                    # once its retry was rejected.
                    (config.STATE / "stop-seat.json").write_text(json.dumps(
                        {"session": "seat", "turn": self.now - 1000, "blocks": 0}))
                    env = {**os.environ, "HOME": str(home), "AGENTKIT_SESSION": "seat"}
                    result = subprocess.run(["bash", str(REPO / "hooks/orchestrator-stop.sh")],
                                            input=payload, text=True, capture_output=True,
                                            env=env, cwd=self.root, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if run.going(state, now=self.now):
                        self.assertEqual(result.stdout, "")
                    else:
                        self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def test_parked_waiting_rechecks_admission_after_fetch(self):
        directory = self.receipt("20260923-1213-race", state="waiting",
                                 waiting_on={"ref": "origin/main", "sha": "0" * 40})

        def fetch(*_args):
            run.save_state(directory, {**run.read_state(directory),
                                       "handed_back": self.now})
            return "1" * 40

        with patch.object(run, "upstream_sha", side_effect=fetch), \
                patch.object(run, "spawn_bg",
                             side_effect=AssertionError("handed back during fetch")):
            watch.resume_waiting(log=self.log, now=self.now)
        self.assertNotIn("waiting_resume_at", run.read_state(directory))
        self.assertEqual(self.logs, [])

    def test_parked_stale_schedules_do_not_keep_seats_working_or_history_listed(self):
        for word in ("error", "waiting"):
            with self.subTest(word=word):
                directory = self.receipt(f"20260923-1214-stale-{word}", state=word,
                                         finished_at=self.now - 86401,
                                         error_retry_at=self.now - 1, error_retries=2)
                state = run.read_state(directory)
                found = watch.session_state(
                    "seat", self.now, session={"name": "seat"}, cfg=self.cfg,
                    records=[(directory, state)], live={}, auth_out={}, gh_out={},
                    token_out={}, previous={})
                self.assertEqual(found["word"], "needs you")
                self.assertEqual(found["reason"], run.parked_line(state, now=self.now)
                                 if word == "error" else "waiting for you")
                self.assertEqual(menu.v5o_needs_look(state, now=self.now), word == "error")
                run.save_state(directory, {**state, "finished_at": self.now - run.GC_AGE - 1})
                with redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(run.cmd_status([]), 0)
                self.assertNotIn(directory.name, out.getvalue())
                with redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(run.cmd_status([directory.name]), 0)
                self.assertIn(f"run {directory.name} parked:", out.getvalue())
                self.assertNotIn("retry due", out.getvalue())
                if word == "error":
                    self.assertNotIn("error_retry_at", run.read_state(directory))
                    self.assertNotIn("error_retries", run.read_state(directory))

    def test_parked_recent_conflict_from_renamed_session_still_parks(self):
        directory = self.receipt("20260923-1202-renamed", state="fail", verdict="FAIL",
                                 error=None, merge_note=CONFLICT_NOTE,
                                 round_summaries=[{"round": 1}],
                                 finished_at=self.now - 86399, handback_pending=True)
        (directory / "log.txt").write_text(f"not merged: {CONFLICT_NOTE}\n")
        config.rename_session("seat", "renamed")
        with patch.object(run, "upstream_sha", return_value="1" * 40):
            watch.resume_waiting(log=self.log, now=self.now)
        state = run.read_state(directory)
        self.assertEqual(state["state"], "waiting")
        self.assertNotIn("handback_pending", state)
        self.assertIn("session renamed exists", run.parked_line(state, now=self.now))

    def test_parked_tick_resume_keeps_the_sessions_worker_pair(self):
        config.save_session(self.cfg, "seat", "fable", ["astra", "spark"])
        providers = self.providers(openai_used=50, meta_used=60)
        providers["xai"] = {"meters": [meter("weekly", 0, self.now + WEEK)]}
        # Without the saved session's list, the healthy Grok would win this handover.
        self.assertEqual(run.next_executor(self.cfg, providers, {"anthropic"}, "spark",
                                            self.log, workers=["grok", "astra", "spark"])[0],
                         "grok")

        class Picked(Exception):
            pass

        def drive(cfg, directory, opts, log, prior=None):
            # Exercise the real resume's role selection; stop before any worker turn.
            with self.assertRaises(Picked):
                run.loop(cfg, directory, directory / "task.md", opts, log, prior)
            return 0

        for word in ("error", "waiting"):
            with self.subTest(word=word):
                directory = self.receipt(f"20260923-1203-pair-{word}", state=word,
                                         executor="opus",
                                         error_retry_at=self.now - 1,
                                         waiting_on={"ref": "origin/main", "sha": "0" * 40})

                def resume(d, args, expected=None):
                    self.assertEqual(run.read_state(d), expected)
                    return run.cmd_resume(args[1:])

                with patch.object(run, "spawn_bg", side_effect=resume), \
                        patch.object(run, "upstream_sha", return_value="1" * 40), \
                        patch.object(run, "drive", side_effect=drive), \
                        patch.object(run, "collect_usage", return_value=providers), \
                        patch.object(run, "disk_pressure", return_value=False), \
                        patch.object(run, "exclude_junk"), \
                        patch.object(run, "join_session_project"), \
                        patch.object(run, "project_lessons", return_value=""), \
                        patch.object(run, "rounds", side_effect=Picked):
                    if word == "error":
                        watch.resume_errored(log=self.log, now=self.now)
                    else:
                        watch.resume_waiting(log=self.log, now=self.now)
                after = run.read_state(directory)
                self.assertEqual(after["state"], "running")
                self.assertEqual((after["executor"], after["reviewer"]), ("astra", "spark"))
                self.assertEqual(run.run_workers(self.cfg, after), ["astra", "spark"])

    def test_parked_waiting_resume_drops_the_previous_attempts_marks(self):
        # a `waiting` resume is a new attempt like a FAIL's: the delivery note of
        # the attempt it replaces goes before the drive, so a resume that dies
        # before the merge leaves no note describing the previous attempt
        waiter = self.receipt("20260922-1312-again", state="waiting", verdict="FAIL",
                              error=CONFLICT_NOTE, merge_note=CONFLICT_NOTE,
                              merge_failed=True,
                              review_pending={"round": 2, "summary": "old",
                                              "reason": "before the abort dropped it"},
                              round_summaries=[{"round": 1, "verdict": "PASS",
                                                "done_when": True}],
                              waiting_on={"ref": "origin/main", "sha": "0" * 40})
        (waiter / "log.txt").write_text(f"not merged: {CONFLICT_NOTE}\n")
        with patch.object(run, "commit_identity", return_value={}), \
                patch.object(run, "drive", return_value=0):
            self.assertEqual(run.cmd_resume([waiter.name]), 0)
        after = run.read_state(waiter)
        self.assertFalse(after["merge_failed"])
        self.assertIsNone(after["merge_note"])
        self.assertNotIn("review_pending", after)
        self.assertNotIn("waiting_on", after)
        self.assertEqual(after["resume_from"], "waiting")

    def test_parked_stop_ends_a_scheduled_retry(self):
        # the owner's off-switch for the ladder: stopping an error run drops
        # its stamp, and stopping a waiter drops its wait, so the tick that
        # would have resumed them finds nothing to resume
        run_dir = self.receipt("20260923-0200-stop", error_retry_at=self.now + 300,
                               error_retries=1, launched_session="seat")
        waiter = self.receipt("20260923-0201-stopwait", state="waiting", verdict="FAIL",
                              error=CONFLICT_NOTE, merge_note=CONFLICT_NOTE,
                              waiting_on={"ref": "origin/main", "sha": "0" * 40},
                              waiting_resume_at=self.now + 900,
                              launched_session="seat")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run.cmd_stop([run_dir.name]), 0)
            self.assertEqual(run.cmd_stop([waiter.name]), 0)
        for d in (run_dir, waiter):
            after = run.read_state(d)
            self.assertEqual(after["state"], "stopped")
            for key in ("error_retry_at", "error_retries", "waiting_on",
                        "waiting_resume_at", "resume_after"):
                self.assertNotIn(key, after)
            self.assertFalse(run.going(after))
        with patch.object(run, "spawn_bg",
                          side_effect=AssertionError("stopped runs stay stopped")):
            watch.resume_errored(log=self.log, now=self.now + 3600)
            watch.resume_waiting(log=self.log, now=self.now + 3600)
        self.assertEqual(self.logs, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
