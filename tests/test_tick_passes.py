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
from agentkit import leases, logins, matrix, seat_tokens, usage, watch  # noqa: E402
from fixtures.tick import only_passes  # noqa: E402

# The passes of the tick this test runs, in its order: the WARN line a raise of each is told in
# (GitHub's follow the table, under none), and whether a dry run runs it too.
PASSES = (
    (notify, "retry_pending", "the notification retry did not run", True),
    (watch, "resume_after_boot", "the boot resume pass did not run", True),
    (watch, "finish_own_lines", "the held-line Enter pass did not run", False),
    (watch, "continue_turns", "the mid-turn continue pass did not run", False),
    (watch, "health", "the session health pass did not run", True),
    (watch, "resume_dead_loops", "the dead-loop pass did not run", True),
    (watch, "resume_dead_jobs", "the dead-job pass did not run", True),
    (watch, "recover_runs", "the stall pass did not run", True),
    (leases, "scan_all", "the lease scan did not run", False),
    (watch, "save_state", "the tick's watch.json was not saved", False),
    (usage, "collect", "the usage refresh did not finish", False),
    (logins, "remind", "the login-end read did not run", False),
    (watch, "remind_worker_tokens", "the worker-token reminder did not run", False),
    (matrix, "refresh", "the boards pass did not run", False),
    (staffing, "_cached_providers", "the usage refresh did not finish", True),
    (watch, "resume_exhausted", "the exhausted-resume pass did not run", True),
    (watch, "resume_waiting_login", "the login-resume pass did not run", True),
    (watch, "resume_errored", "the error-retry pass did not run", True),
    (watch, "resume_waiting", "the waiting-resume pass did not run", True),
    (watch, "sweep_preexisting", "the pre-existing sweep did not run", False),
    (watch, "offer_endings", "the ending pass did not run", False),
    (jobs, "deliver_job_handbacks", "a finished job was not handed back", False),
    (watch, "wait_over", "the wait pass did not run", False),
    (seat_tokens, "read", "the seat token pass did not run", False),
    (watch, "tell_audit", "the weekly audit pass did not run", False),
    (notify, "tick_cards", "the card transition pass did not run", False),
    (watch, "revive_seats", "the seat revival pass did not run", False),
    (gc, "git_housekeeping", "git housekeeping did not finish", False),
    (gc, "schedule_gc", "retention pass did not finish", False),
    (orch, "stamp", "retention pass did not finish", False),
    (orch, "sweep", "retention pass did not finish", False),
    (browser, "tidy", "browser tidy did not finish", False),
    (update, "go_live", "agentkit did not go live", False),
    (update, "keep_current", "the harness upgrade pass did not run", False),
    (watch, "incoming", None, True), (watch, "outgoing", None, True),
    (watch, "after_merge_checks", None, True),
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
        with only_passes(self.root, *{what for _, _, what, _ in PASSES}), redirect_stdout(out):
            self.assertEqual(watch.main(list(argv)), 0)
        return out.getvalue()

    def test_a_pass_that_raises_is_its_warn_line_and_every_other_pass_still_runs(self):
        for name, error in (("agentkit.notify.retry_pending", OSError("disk")),
                            ("agentkit.watch.health", TypeError("torn seat file")),
                            ("agentkit.browser.tidy", KeyError("tab"))):
            with self.subTest(name=name):
                for mock in self.passes.values():
                    mock.reset_mock()
                self.passes[name].side_effect = error
                said = self.tick()
                self.passes[name].side_effect = None
                self.assertEqual(sum("WARN" in line for line in said.splitlines()), 1, said)
                self.assertIn(f": {error}", said)
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

    def test_the_exhausted_resume_reads_the_usage_this_tick_refreshed(self):
        # the read itself, never a copy: a Readings is what has readiness check the harnesses
        fresh = usage.Readings({"claude": "fresh"})
        self.passes["agentkit.usage.collect"].return_value = fresh
        self.tick()
        self.assertIs(self.passes["agentkit.watch.resume_exhausted"].call_args.args[1], fresh)
        self.passes["agentkit.usage.collect"].side_effect = OSError("meter")
        self.assertIn("WARN the usage refresh did not finish: meter", self.tick())
        self.assertEqual(self.passes["agentkit.watch.resume_exhausted"].call_args.args[1], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
