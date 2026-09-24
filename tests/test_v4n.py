"""Menu fixtures, run reporting, Codex rollouts and launch/cache regressions; offline."""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, run, terminal, usage
from agentkit.harness import codex as codex_plugin


class Sandbox(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v4n-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root),
                                 "NO_COLOR": "1", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                                 # this HOME's OpenCode config, never the caller's: mimo is payg
                                 "OPENCODE_CONFIG_DIR": str(self.root / ".config/opencode")}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[]))
        self.stack.enter_context(patch.object(terminal, "height", return_value=24))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=10000))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        self.cfg = config.load()
        config.ensure_dirs()

    def ended(self, name, owner="gone-seat", **extra):
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "title": f"Finished {name}", "state": "pass",
                 "verdict": "PASS", "launched_session": owner, "reported": False,
                 "executor": "opus", "reviewer": "astra",
                 "review": {"executor": "opus", "reviewer": "astra", "returncode": 0,
                            "executor_provider": config.model(self.cfg, "opus")["provider"],
                            "reviewer_provider": config.model(self.cfg, "astra")["provider"],
                            "verdict": "PASS", "done_when": True},
                 "finished_at": 9990, **extra}
        run.save_state(directory, state)
        return directory

    def rollout(self, filename, cwd, stamp, sid="thread", **extra):
        root = self.root / ".codex/sessions/2026/09/10"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"rollout-{filename}.jsonl"
        path.write_text(json.dumps({"type": "session_meta", "payload": {
            "cwd": str(cwd), "timestamp": stamp, "id": sid, **extra}}) + "\n")
        return path


class RunReporting(Sandbox):
    def test_menu_draw_leaves_endings_unreported_for_the_orchestrator(self):
        visible = self.ended("visible")
        old = self.ended("old", finished_at=10000 - menu.RUNS_RECENT - 1)
        smoke = self.ended("smoke-ignored")
        with redirect_stdout(io.StringIO()):
            menu.draw(self.cfg, [])
        self.assertFalse(run.read_state(visible)["reported"])
        self.assertFalse(run.read_state(old)["reported"])
        self.assertFalse(run.read_state(smoke)["reported"])
        later = self.ended("later")
        self.assertFalse(run.read_state(later)["reported"])
        # `ak run status <id>` marks one ending looked at.
        with redirect_stdout(io.StringIO()):
            run.cmd_status(["visible"])
        self.assertTrue(run.read_state(visible).get("recovery_acknowledged_at"))


class CodexSeats(Sandbox):
    def test_directory_and_metadata_time_never_establish_ownership(self):
        record = {"orchestrator": "astra", "cwd": str(self.root), "created": 100}
        self.rollout("z-old", self.root, "1970-01-01T00:01:39Z", "old")
        self.rollout("same-time", self.root, "1970-01-01T00:01:40Z", "same")
        self.rollout("wrong", self.root / "other", "1970-01-01T00:30:00Z", "wrong")
        self.rollout("z-first", self.root, "1970-01-01T00:02:00Z", "first")
        self.rollout("a-newest", self.root, "1970-01-01T02:03:00+02:00", "newest")
        broken = self.rollout("broken", self.root, "bad")
        broken.write_text('{"type":')
        self.rollout("no-id", self.root, "1970-01-01T00:30:00Z", None)
        self.assertIsNone(orch.seat_conversation(record))
        self.assertIsNone(orch.seat_conversation({**record, "created": 0}))
        self.assertIsNone(orch.seat_conversation({**record, "created": None}))
        self.assertIsNone(orch.seat_conversation({**record, "orchestrator": "spark"}))

    def test_gone_and_exited_codex_seats_resume_the_selected_thread(self):
        config.save_session(self.cfg, "codex-seat", "astra", ["opus"],
                            {"cwd": str(self.root), "created": 100})
        path = self.rollout("new", self.root, "1970-01-01T00:03:00Z", "seat-thread")
        receipt = codex_plugin.prepare("codex-seat", self.root, None)
        codex_plugin.capture(receipt, {"hook_event_name": "SessionStart", "source": "startup",
                                  "session_id": "seat-thread", "transcript_path": str(path),
                                  "cwd": str(self.root)})
        for seats in ([], [{"name": "codex-seat", "exited": True, "path": str(self.root),
                           "created": 100}]):
            with self.subTest(seats=seats), patch.object(orch, "sessions", return_value=seats):
                self.assertTrue(orch.listing()[0]["resumable"])
                # Nobody is in it: the seat needs him, and its number is the way back in.
                self.assertEqual(menu.state(orch.listing()[0]), "needs you")
                logs = []
                with patch.object(orch, "launch") as launch, patch.object(orch, "attach"):
                    orch.resume(self.cfg, "codex-seat", log=logs.append)
                cmd = launch.call_args.args[3]
                self.assertEqual(cmd[cmd.index("resume"):cmd.index("resume") + 2],
                                 ["resume", "seat-thread"])
                self.assertIn("conversation seat-thread", logs[0])

    def test_no_qualifying_rollout_starts_fresh_and_explains_it(self):
        config.save_session(self.cfg, "codex-seat", "astra", ["opus"],
                            {"cwd": str(self.root), "created": 100,
                             "conversation": "stale-guess"})
        self.rollout("old", self.root, "1970-01-01T00:01:00Z", "old")
        logs = []
        with patch.object(orch, "launch") as launch, patch.object(orch, "attach"):
            orch.resume(self.cfg, "codex-seat", log=logs.append)
        self.assertNotIn("resume", launch.call_args.args[3])
        self.assertIsNone(launch.call_args.args[4])
        self.assertIn("Codex ownership unverified; it starts fresh", logs[0])
        # The receipt is still a fact the resume reads; it is no state the row says.
        self.assertEqual(menu.state(orch.listing()[0]), "needs you")


class LaunchAndCache(Sandbox):
    def test_launch_owner_precedes_preflight_and_survives_background_fork(self):
        task = self.root / "task.md"
        task.write_text("---\nrounds: 1\n---\n# Task\n\n## Done when\n```bash\ntrue\n```\n")
        for args in ([str(task), "--bg"], ["--review-pr", "https://github.com/o/r/pull/1", "--bg"]):
            with self.subTest(args=args), patch.object(config, "current_session", return_value="seat"):
                def preflight(directory, *_):
                    self.assertEqual(run.read_state(directory)["launched_session"], "seat")
                    return None
                with patch.object(run, "preflight", side_effect=preflight), \
                        patch.object(run.subprocess, "Popen", **{"return_value.pid": 99999999}), \
                        redirect_stdout(io.StringIO()):
                    run.main(args)
                    self.assertEqual(run.read_state(run.run_dirs()[-1])["pid"], 99999999)
        for directory in run.run_dirs():
            with patch.object(config, "current_session", return_value="different"):
                self.assertEqual(run.launch_session(directory), "seat")
        directory = self.ended("unowned", owner=None)
        with patch.object(config, "current_session", return_value="different"):
            self.assertIsNone(run.launch_session(directory))

    def test_names_normalize_on_creation_lookup_and_rename(self):
        with patch.object(orch, "alias_names", return_value=set()), \
                patch.object(usage, "collect", return_value={}), \
                patch.object(orch, "launch"), redirect_stdout(io.StringIO()):
            orch.create(self.cfg, "  My   Seat\t ", self.root, forced="astra", forced_workers="opus")
        self.assertTrue(config.session_path("my-seat").exists())
        self.assertEqual(config.resolve_session("  My \t Seat  "), "my-seat")
        config.rename_session("my-seat", "renamed")
        self.assertEqual(config.resolve_session(" My   Seat "), "renamed")
        config.save_session(self.cfg, "  legacy   name ", "astra", ["opus"])
        self.assertEqual(config.resolve_session(" legacy \t name "), "legacy name")
        with patch.object(orch, "sessions", return_value=[{"name": "renamed"}]):
            self.assertIsNone(orch.find("my-seat"))  # the old alias still cannot start a new seat
        with patch.object(orch, "sessions", return_value=[{"name": "legacy name"}]):
            self.assertEqual(orch.find(" legacy   name ")["name"], "legacy name")

    def test_failed_preflight_keeps_its_owner_and_is_finished(self):
        directory = config.RUNS / "preflight-error"
        directory.mkdir()
        with patch.object(config, "current_session", return_value="seat"), \
                patch.object(run, "preflight", side_effect=config.Error("bad base")):
            with self.assertRaisesRegex(config.Error, "bad base"):
                run.prepare(directory, {}, lambda _: None)
        state = run.read_state(directory)
        self.assertEqual(state["launched_session"], "seat")
        self.assertEqual(state["state"], "error")
        self.assertEqual(state["finished_at"], 10000)

    def test_first_usage_read_fills_old_cache_before_printing_without_spending(self):
        providers = {"openai": {"harness": "codex", "meters": [], "error": None}}
        usage._store(config.STATE / "usage.json", 9999, providers)
        with patch.object(usage, "_adapter_json", return_value={"available": 3}) as adapter, \
                patch.object(usage, "_maybe_reset") as spend, redirect_stdout(io.StringIO()) as out:
            usage.main([])
        self.assertEqual(adapter.call_args.args[:2], ("codex", "reset-status"))
        spend.assert_not_called()
        cached = json.loads((config.STATE / "usage.json").read_text())
        self.assertEqual(cached["providers"]["openai"]["resets"], 3)
        self.assertEqual(cached["fetched_at"], 9999)
        self.assertIn("3", out.getvalue())

    def test_install_options_include_remain_on_exit_for_legacy_target(self):
        # Run the installer's actual option function against a recorder, not a tmux server.
        source = (REPO / "install.sh").read_text()
        function = source[source.index("tmux_options() {"):source.index("\nif have tmux;",
                                                                         source.index("tmux_options() {"))]
        script = 'ak_tmux() { printf "%s\\n" "$*"; }\n' + function
        script += '\ntmux_options legacy "" -t legacy-seat\n'
        self.assertIn('tmux_options "the legacy seat $legacy on the default server" "" -t "$legacy"',
                      source)
        proc = subprocess.run(["bash", "-c", script],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # The function captures its successful command output; trace the exact invocation.
        proc = subprocess.run(["bash", "-x", "-c", script], capture_output=True, text=True)
        self.assertIn("ak_tmux '' set -t legacy-seat remain-on-exit on", proc.stderr)


class Rendering(Sandbox):
    def fixture(self, width):
        rows = [["1", "customer-portal-app", "astra", "needs you",
                 "Review the deployment proposal before we publish the next version", "3h"],
                ["2", "parser", "fable", "working", "Implement the parser improvements", "20m"],
                ["3", "archive", "astra", "resumable", "", "2d"]]
        providers = {
            "anthropic": {"harness": "claude", "resets": 0, "error": None, "meters": [
                {"name": "weekly_all", "used": 45, "elapsed": 50, "window_secs": 604800},
                {"name": "session", "used": 20, "elapsed": 40, "window_secs": 18000}]},
            "openai": {"harness": "codex", "resets": 3, "error": None, "meters": [
                {"name": "weekly", "used": 60, "elapsed": 40, "window_secs": 604800}]},
            "meta": {"harness": "muse", "resets": 0, "error": "unknown: no usage endpoint",
                     "meters": []}}
        self.ended("receipt", owner="customer-portal-app", merged=True)
        out = io.StringIO()
        with patch.object(terminal, "width", return_value=width), \
                patch.object(menu, "row", side_effect=rows), \
                patch.object(menu, "installed", return_value="abc1234 · 15 Sep"), \
                patch.object(menu.time, "strftime", return_value="14:02"), redirect_stdout(out):
            (config.STATE / "usage.json").write_text(json.dumps(
                {"fetched_at": 10000, "providers": providers}))
            menu.draw(self.cfg, [{"name": "customer-portal-app"}, {"name": "parser"}, {"name": "archive"}])
            print("\nRuns:")
            menu.table([["1", "Implement the reviewed deployment proposal", "customer-portal-app",
                         "working", "opus/astra 2/3", "15m"],
                        ["2", "Fix the parser", "parser", "done", "spark/fable 1/1 · merged", "2h"]])
            print("\nUsage:")
            print(usage.render(self.cfg, providers, ["astra", "opus", "spark"]))
        return out.getvalue()

    def test_rendered_fixtures_fit_phone_and_laptop_widths(self):
        for width in (40, 80, 100):
            with self.subTest(width=width):
                rendered = self.fixture(width)
                # Exact current menu snapshots live in v5o; retain these wider table checks.
                self.assertTrue(all(terminal.cells(line) <= width for line in rendered.splitlines()))
                self.assertNotIn("\033", rendered)
                for phrase in menu.KEYS.split("   "):
                    self.assertIn(phrase, rendered)
                # Rows carry one of the three words and nothing else; these three
                # seats are all live, so none of them says its session is closed.
                self.assertIn("needs you", rendered)
                self.assertNotIn("session closed", rendered.split("\nRuns:")[0])
                (config.RUNS / "receipt/run.json").unlink()
                (config.RUNS / "receipt").rmdir()

    def test_unicode_long_fields_and_word_boundaries(self):
        self.assertEqual(terminal.cut("hello wonderful world", 10), "hello…")
        self.assertEqual(terminal.cut("hello wonderful world", 12), "hello wonde…")
        self.assertEqual(terminal.cut("hello world next", 12), "hello world…")
        for width in (40, 80, 100):
            rows = [["100", "界" * 40, "a" * 100, "needs you", "e\u0301 " * 80, "999d"]]
            self.assertTrue(all(terminal.cells(line) <= width for line in terminal.seats(rows, width)))

    def test_waiting_and_legacy_details_do_not_invent_states(self):
        # A seat the watchdog is waiting out is still one of the three words, and its
        # row's last column is the reason for that word -- never a state of its own.
        with patch.object(menu.notify, "last", return_value=None), \
                patch("agentkit.watch.load_state", return_value={"stalls": {
                    "legacy-seat": {"status": "waiting until 2026-09-10 14:00"}}}):
            row = menu.row(self.cfg, 1, {"name": "legacy-seat", "legacy": True, "created": 100})
        self.assertIn(row[3], terminal.STATES)
        self.assertEqual(row[4], "waiting for you")

    def test_job_feedback_shortens_home_before_truncating_the_log_name(self):
        notice = f"update: FAILED ({self.root}/.agentkit/tmp/update-20260910-140200.log)"
        with patch.object(terminal, "width", return_value=100), \
                patch.object(menu.orch, "job_notices", return_value=[notice]), \
                patch.object(menu, "read", return_value="q"), redirect_stdout(io.StringIO()) as out:
            menu.loop(self.cfg, dry_run=True)
        self.assertIn("update: FAILED (~/.agentkit/tmp/update-20260910-140200.log)", out.getvalue())
        self.assertTrue(all(terminal.cells(line) <= 100 for line in out.getvalue().splitlines()))

    def test_colour_only_for_a_capable_terminal(self):
        with patch.object(sys.stdout, "isatty", return_value=True):
            for env in ({"TERM": "dumb"}, {"TERM": "xterm-256color", "NO_COLOR": ""}, {}):
                with patch.dict(os.environ, env, clear=True):
                    self.assertEqual(terminal.styled("state", "accent"), "state")
            with patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
                self.assertEqual(terminal.styled("state", "accent"), "\033[38;5;111mstate\033[0m")


if __name__ == "__main__":
    unittest.main()
