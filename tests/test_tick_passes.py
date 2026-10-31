"""The tick is one list of passes: a pass that raises is one WARN line, and the next one runs.

Offline: every pass is a mock over a temporary ~/.agentkit, and gh answers with a login.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import browser, config, gc, job as jobs, notify, orch, run, staffing, update  # noqa: E402
from agentkit import leases, logins, seat_tokens, usage, watch  # noqa: E402
from fixtures.tick import only_passes  # noqa: E402

# The passes of the tick this test runs, in its order: the name a raise of each is told by
# (GitHub's follow the table, under none), and whether a dry run runs it too.
PASSES = (
    (watch, "after_merge_checks", "merge checks", True),
    (notify, "retry_pending", "notification retry", True),
    (watch, "resume_after_boot", "boot resume", True),
    (watch, "finish_own_lines", "held lines", False),
    (watch, "continue_turns", "rebooted turns", False),
    (watch, "continue_turns", "switched turns", False),
    (watch, "health", "seat health", True),
    (watch, "resume_dead_loops", "dead loops", True),
    (watch, "resume_dead_jobs", "dead jobs", True),
    (watch, "recover_runs", "stall recovery", True),
    (leases, "scan_all", "lease scan", False),
    (watch, "save_state", "state save", False),
    (usage, "collect", "usage refresh", False),
    (logins, "remind", "login reminder", False),
    (watch, "remind_worker_tokens", "token reminder", False),
    (staffing, "_cached_providers", "usage refresh", True),
    (watch, "resume_exhausted", "exhausted resume", True),
    (watch, "resume_waiting_login", "login resume", True),
    (watch, "resume_errored", "error retry", True),
    (watch, "resume_waiting", "waiting resume", True),
    (watch, "sweep_preexisting", "old endings", False),
    (watch, "offer_endings", "endings", False),
    (jobs, "deliver_job_handbacks", "job handbacks", False),
    (watch, "wait_over", "ended waits", False),
    (seat_tokens, "read", "seat tokens", False),
    (watch, "tell_audit", "weekly audit", False),
    (notify, "tick_cards", "card transitions", False),
    (watch, "revive_seats", "seat revival", False),
    (gc, "git_housekeeping", "git housekeeping", False),
    (gc, "schedule_gc", "collection", False),
    (orch, "stamp", "exit clocks", False),
    (orch, "sweep", "seat sweep", False),
    (browser, "tidy", "browser tidy", False),
    (update, "go_live", "live update", False),
    (update, "keep_current", "harness upgrade", False),
    (watch, "incoming", None, True), (watch, "outgoing", None, True),
)


class TickPasses(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-tick-passes-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        self.stack.enter_context(patch.object(watch, "LOG_OWNED", set()))
        config.ensure_dirs()
        self.stack.enter_context(patch.object(watch, "gh_json", return_value=({"login": "me"}, "")))
        self.passes = {f"{where.__name__}.{name}": self.stack.enter_context(
            patch.object(where, name, return_value={} if name in ("collect", "_cached_providers")
                         else None)) for where, name, _what, _dry in PASSES}

    def tick(self, *argv):
        out = io.StringIO()
        with only_passes(self.root, *{what for _, _, what, _ in PASSES if what}), redirect_stdout(out):
            self.assertEqual(watch.main(list(argv)), 0)
        return out.getvalue()

    def test_a_pass_that_raises_is_its_warn_line_and_every_other_pass_still_runs(self):
        for name, what, error in (
                ("agentkit.notify.retry_pending", "notification retry", OSError("disk")),
                ("agentkit.watch.health", "seat health", TypeError("torn seat file")),
                ("agentkit.browser.tidy", "browser tidy", KeyError("tab"))):
            with self.subTest(name=name):
                for mock in self.passes.values():
                    mock.reset_mock()
                self.passes[name].side_effect = error
                said = self.tick()
                self.passes[name].side_effect = None
                self.assertEqual(sum("WARN" in line for line in said.splitlines()), 1, said)
                self.assertIn(f"WARN {what} did not run: {error}\n", said)
                for other, mock in self.passes.items():
                    if other != "agentkit.staffing._cached_providers":
                        self.assertTrue(mock.called, f"{other} did not run after {name}")

    def test_a_dry_run_runs_only_the_passes_that_change_nothing(self):
        self.tick("--dry-run")
        for where, name, _what, dry in PASSES:
            with self.subTest(name=name):
                self.assertEqual(self.passes[f"{where.__name__}.{name}"].called, dry, name)
        self.assertTrue(self.passes["agentkit.watch.health"].call_args.args[2])
        for name in ("resume_exhausted", "resume_waiting_login", "resume_errored",
                     "resume_waiting"):
            self.assertIs(self.passes[f"agentkit.watch.{name}"].call_args.kwargs["dry_run"], True)

    def test_the_tick_reads_no_board(self):
        # the owner, 22 Oct 2026: "It should not be a 24/7 running process, but isntead more
        # like a feature"; the models screen and `ak models` read the boards
        out = io.StringIO()
        with only_passes(self.root), redirect_stdout(out), \
                patch("agentkit.matrix.refresh", side_effect=AssertionError("the tick read")):
            self.assertEqual(watch.main([]), 0)
        self.assertNotIn("the tick read", out.getvalue())

    def test_the_exhausted_resume_reads_the_usage_this_tick_refreshed(self):
        # the read itself, never a copy: a Readings is what has readiness check the harnesses
        fresh = usage.Readings({"claude": "fresh"})
        self.passes["agentkit.usage.collect"].return_value = fresh
        self.tick()
        self.assertIs(self.passes["agentkit.watch.resume_exhausted"].call_args.args[1], fresh)
        self.passes["agentkit.usage.collect"].side_effect = OSError("meter")
        self.assertIn("WARN usage refresh did not run: meter", self.tick())
        self.assertEqual(self.passes["agentkit.watch.resume_exhausted"].call_args.args[1], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
