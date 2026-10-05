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
from agentkit import browser, config, gc, job as jobs, notify, orch, run, tell, update  # noqa: E402
from agentkit import usage, watch  # noqa: E402

# Every pass of the tick, in its order, and whether a dry run runs it too.
PASSES = (
    (notify, "retry_pending", True), (watch, "resume_after_boot", True),
    (watch, "continue_turns", False), (watch, "health", True),
    (watch, "resume_dead_loops", True), (watch, "resume_dead_jobs", True),
    (watch, "recover_runs", True), (watch, "save_state", False), (usage, "collect", False),
    (run, "_cached_providers", True), (watch, "resume_exhausted", True),
    (watch, "resume_waiting_login", True), (watch, "resume_errored", True),
    (watch, "resume_waiting", True), (watch, "sweep_preexisting", False),
    (watch, "offer_endings", False), (jobs, "deliver_job_handbacks", False),
    (watch, "tell_waits", False), (tell, "deliver", False), (notify, "tick_cards", False),
    (watch, "revive_seats", False), (gc, "schedule_gc", False), (orch, "stamp", False),
    (orch, "sweep", False), (browser, "tidy", False), (update, "go_live", False),
    (update, "keep_current", False), (watch, "incoming", True), (watch, "outgoing", True),
    (watch, "after_merge_checks", True),
)


class TickPasses(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-tick-passes-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        self.stack.enter_context(patch.object(watch, "LOG_OWNED", set()))
        config.ensure_dirs()
        self.stack.enter_context(patch.object(watch, "gh_json", return_value=({"login": "me"}, "")))
        self.passes = {f"{where.__name__}.{name}": self.stack.enter_context(
            patch.object(where, name, return_value={} if name in ("collect", "_cached_providers")
                         else None)) for where, name, _dry in PASSES}

    def tick(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
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
                    if other != "agentkit.run._cached_providers":
                        self.assertTrue(mock.called, f"{other} did not run after {name}")

    def test_a_dry_run_runs_only_the_passes_that_change_nothing(self):
        self.tick("--dry-run")
        for where, name, dry in PASSES:
            with self.subTest(name=name):
                self.assertEqual(self.passes[f"{where.__name__}.{name}"].called, dry, name)
        self.assertTrue(self.passes["agentkit.watch.health"].call_args.args[2])
        for name in ("resume_exhausted", "resume_waiting_login", "resume_errored",
                     "resume_waiting"):
            self.assertIs(self.passes[f"agentkit.watch.{name}"].call_args.kwargs["dry_run"], True)

    def test_the_exhausted_resume_reads_the_usage_this_tick_refreshed(self):
        self.passes["agentkit.usage.collect"].return_value = {"claude": "fresh"}
        self.tick()
        self.assertEqual(self.passes["agentkit.watch.resume_exhausted"].call_args.args[1],
                         {"claude": "fresh"})
        self.passes["agentkit.usage.collect"].side_effect = OSError("meter")
        self.assertIn("WARN the usage refresh did not finish: meter", self.tick())
        self.assertEqual(self.passes["agentkit.watch.resume_exhausted"].call_args.args[1], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
