"""Seats stop only their own work; the owner can stop anything. Offline, fake HOME and kills."""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import browser, config, job, notify, orch, record, run, watch


class StopOwnRunsOnly(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            config.SESSION_ENV: "acme-api", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        for name in ("acme-api", "acme-ui"):
            config.save_session(self.cfg, name, "opus", ["opus", "astra"])
        self.stack.enter_context(patch.object(orch, "records", side_effect=config.session_records))
        self.stack.enter_context(patch.object(orch, "seat_plugin"))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=True))
        self.stack.enter_context(patch.object(orch, "bus_env", return_value=dict(os.environ)))
        self.systemctl = self.stack.enter_context(patch.object(
            run.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")))
        self.tmux = self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.card = self.stack.enter_context(patch.object(notify, "forget_card"))
        self.tabs = self.stack.enter_context(patch.object(browser, "close_owned"))
        self.checkout = self.stack.enter_context(patch.object(run, "stop_checkout", return_value=True))
        self.kill = self.stack.enter_context(patch.object(watch, "kill_tree"))
        self.stack.enter_context(patch.object(run, "marker_pids", return_value=[4242]))
        self.stack.enter_context(patch.object(record, "process_active", return_value=True))
        for name in ("history_finish", "record_result", "redress_seat", "drop_checkout"):
            self.stack.enter_context(patch.object(run, name))

    def running(self, name, owner, *, in_job=False, legacy=False):
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "state": "running", "pid": 4241,
                 "session" if legacy else "launched_session": owner}
        if in_job:
            job_dir = config.JOBS / f"{name}-job"
            job_dir.mkdir(parents=True)
            job.save_job(job_dir, {"job_id": job_dir.name, "seat": owner, "pid": 4241,
                                   "tasks": [{"name": "fix-api.md", "run_id": name,
                                              "state": "running"}]})
            state["job_id"] = job_dir.name
        record.save_state(directory, state)
        return directory

    def unchanged_on_refusal(self, command, owner):
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with redirect_stdout(io.StringIO()), self.assertRaises(config.Error) as refused:
            command()
        self.assertIn(owner, str(refused.exception))
        self.assertIn("message", str(refused.exception).lower())
        for path, contents in before.items():
            self.assertEqual(path.read_bytes(), contents, path)
        for action in (self.systemctl, self.tmux, self.card, self.tabs, self.checkout, self.kill):
            action.assert_not_called()

    def stop_run(self, directory):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(["stop", directory.name]), 0)
        self.assertEqual(record.read_state(directory)["state"], "stopped")

    def test_other_seats_runs_are_refused_including_job_tasks_and_legacy_receipts(self):
        for in_job in (False, True):
            for legacy in (False, True):
                with self.subTest(in_job=in_job, legacy=legacy):
                    directory = self.running(f"fix-api-{in_job}-{legacy}", "acme-ui",
                                             in_job=in_job, legacy=legacy)
                    self.unchanged_on_refusal(
                        lambda: run.main(["stop", directory.name, "--keep"]), "acme-ui")

    def test_own_and_seatless_runs_still_stop_including_job_tasks(self):
        for in_job in (False, True):
            for owner in ("acme-api", None):
                with self.subTest(in_job=in_job, owner=owner):
                    directory = self.running(f"fix-api-{in_job}-{owner}", owner, in_job=in_job)
                    self.stop_run(directory)
        self.kill.assert_called()
        self.systemctl.assert_called()
        self.checkout.assert_called()
        self.tabs.assert_called()

    def test_owner_can_stop_other_seats_runs_without_session(self):
        os.environ.pop(config.SESSION_ENV)
        for in_job in (False, True):
            with self.subTest(in_job=in_job):
                self.stop_run(self.running(f"fix-api-{in_job}", "acme-ui", in_job=in_job))

    def test_renames_preserve_run_ownership_and_refusal_names_current_seat(self):
        config.rename_session("acme-api", "api-now")
        config.rename_session("acme-ui", "ui-now")
        other = self.running("fix-ui", "acme-ui")
        self.unchanged_on_refusal(lambda: run.main(["stop", other.name]), "ui-now")
        self.stop_run(self.running("fix-api", "acme-api", legacy=True))

    def test_run_owner_is_checked_again_under_the_lock(self):
        directory = self.running("fix-api", "acme-api")
        initial = record.read_state(directory)
        current = {**initial, "launched_session": "acme-ui"}
        with patch.object(record, "read_state", side_effect=[initial, current]), \
                patch.object(record, "save_state") as save:
            self.unchanged_on_refusal(lambda: run.main(["stop", directory.name]), "acme-ui")
        save.assert_not_called()

    def test_other_seat_cannot_be_stopped_or_closed_even_without_tmux(self):
        self.running("fix-ui", "acme-ui", in_job=True)
        for exited in (False, True, None):
            with self.subTest(exited=exited):
                seats = [] if exited is None else [{"name": "acme-ui", "exited": exited}]
                with patch.object(orch, "sessions", return_value=seats), \
                        patch.object(run, "stop_owned_runs") as stop_runs, \
                        patch.object(run, "release_session") as release:
                    self.unchanged_on_refusal(lambda: orch.main(["stop", "acme-ui"]), "acme-ui")
                stop_runs.assert_not_called()
                release.assert_not_called()

    def test_renamed_seat_cannot_be_closed_through_its_old_name(self):
        config.rename_session("acme-ui", "ui-now")
        self.unchanged_on_refusal(lambda: orch.main(["stop", "acme-ui"]), "ui-now")

    def test_own_seat_and_owner_stops_still_close_seats_and_their_runs(self):
        for caller, exited in (("acme-api", False), ("acme-api", True),
                               ("acme-api", None), (None, False)):
            with self.subTest(caller=caller, exited=exited):
                name = f"api-{caller}-{exited}"
                config.save_session(self.cfg, name, "opus", ["opus", "astra"])
                if caller:
                    os.environ[config.SESSION_ENV] = name
                    config.rename_session(name, name + "-now")
                    resolved = name + "-now"
                else:
                    os.environ.pop(config.SESSION_ENV)
                    resolved = name
                mine = self.running(name, name, in_job=True)
                other = self.running(name + "-other", "acme-ui")
                seats = [] if exited is None else [{"name": resolved, "exited": exited}]
                with patch.object(orch, "sessions", return_value=seats), redirect_stdout(io.StringIO()):
                    self.assertEqual(orch.main(["stop", name]), 0)
                self.assertEqual(record.read_state(mine)["state"], "stopped")
                self.assertEqual(record.read_state(other)["state"], "running")
                self.assertFalse(config.session_path(name).exists())
                self.assertFalse(config.session_path(resolved).exists())
                self.assertTrue(config.session_path("acme-ui").exists())
                if exited is not None:
                    self.tmux.assert_any_call("kill-session", "-t", f"={resolved}", socket="agentkit-test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
