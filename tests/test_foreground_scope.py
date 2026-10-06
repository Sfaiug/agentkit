"""A foreground `ak run --no-merge` runs in its own scope, under the cap a `--bg` run gets.

Offline: a fake `busctl` on PATH records what the manager is asked and, as the manager would,
names the new scope in the file this process reads its own cgroup from; `systemd-run` and
`systemctl` beside it only record that something reached them.  No unit is made, and all
signals sent go only to child processes of this test's own.
"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import patch
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import config, host, orch, run
from agentkit import record

USER = f"/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"
SEAT = f"0::{USER}/agentkit.slice/agentkit-test.slice/agentkit-test-seats.slice/acme.scope\n"
BUSCTL = """#!/usr/bin/env python3
import json, os, sys, time
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(["busctl", *sys.argv[1:]]) + "\\n")
if os.environ.get("FAKE_REFUSE"):
    sys.stderr.write(os.environ["FAKE_REFUSE"] + "\\n")
    sys.exit(1)
unit = sys.argv[sys.argv.index("fail") - 1]
if os.environ.get("FAKE_QUEUE"):
    # the manager queued the move as a job, and the reply is lost or never comes in time
    with open(os.environ["FAKE_CGROUP"] + ".queued", "w") as queued:
        queued.write(unit)
    if os.environ["FAKE_QUEUE"] == "timeout":
        time.sleep(5)
    sys.stderr.write("Failed to receive reply: Connection reset by peer\\n")
    sys.exit(1)
with open(os.environ["FAKE_CGROUP"], "w") as cgroup:
    cgroup.write(f"0::{os.environ['FAKE_USER']}/agentkit.slice/agentkit-test.slice/"
                 f"agentkit-test-runs.slice/{unit}\\n")
if os.environ.get("FAKE_LOST"):
    sys.stderr.write("Failed to receive reply: Connection reset by peer\\n")
    sys.exit(1)
"""
RECORDER = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps([os.path.basename(sys.argv[0]), *sys.argv[1:]]) + "\\n")
sys.exit(1)
"""


class ForegroundScope(Sandbox):
    def setUp(self):
        super().setUp()
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", config.SESSION_ENV):
            os.environ.pop(name, None)     # Sandbox's patch.dict puts them back
        fakes = self.root / "fake-bin"
        fakes.mkdir()
        for name, text in (("busctl", BUSCTL), ("systemd-run", RECORDER),
                           ("systemctl", RECORDER)):
            (fakes / name).write_text(text)
            (fakes / name).chmod(0o755)
        self.calls = self.root / "calls.jsonl"
        self.own = self.root / "own-cgroup"
        self.own.write_text(SEAT)
        self.stack.enter_context(patch.dict(os.environ, {
            "PATH": f"{fakes}:{os.environ['PATH']}", "FAKE_LOG": str(self.calls),
            "FAKE_CGROUP": str(self.own), "FAKE_USER": USER, config.RUN_DIR_ENV: "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.stack.enter_context(patch.object(host, "OWN_CGROUP", self.own))
        self.stack.enter_context(patch.object(orch, "scope_oom_policy", return_value=True))
        # a refusal is waited on as long as any answer; the fake busctl still starts in time
        self.stack.enter_context(patch.object(orch, "SLICE_WAIT", 2))
        self.stack.enter_context(patch.object(run, "redress_seat"))
        # `ak run` itself, not this test: only that process is a run's to move
        self.stack.enter_context(patch.object(sys, "argv", [str(REPO / "bin" / "ak"), "run"]))
        self.niced, self.renice = [], None

        def nice(step):
            self.niced.append(step)
            if self.renice:
                raise self.renice

        self.stack.enter_context(patch.object(run.os, "nice", side_effect=nice))
        (config.HOME / "config.toml").write_text("run_memory_max_mb = 512\n")
        self.task = self.root / "fix-api.md"
        self.task.write_text("---\nrepo: none\n---\n# Fix the API\n\n"
                             "## Done when\n```bash\ntrue\n```\n")

    def launch(self, manager=True):
        """`ak run fix-api.md` in the foreground; what the loop found when it started."""
        seen = {}

        def loop(_cfg, run_dir, _opts, _log, **_kw):
            seen.update(pid=os.getpid(), run_dir=run_dir, state=record.read_state(run_dir))
            return 0

        out = io.StringIO()
        with patch.object(orch, "user_manager", return_value=manager), \
                patch.object(run, "drive", side_effect=loop), redirect_stdout(out):
            self.assertEqual(run.main([str(self.task), "--no-merge"]), 0)
        seen["out"] = out.getvalue()
        seen["log"] = (seen["run_dir"] / "log.txt").read_text()
        return seen

    def called(self):
        if not self.calls.exists():
            return []
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def scope_lines(self, text):
        return [line.split("] ", 1)[1] for line in text.splitlines() if "] scope: " in line]

    def test_the_loop_runs_here_in_the_scope_a_bg_run_gets(self):
        seen = self.launch()
        unit = f"agentkit-run-{seen['run_dir'].name}"
        # the loop is this very process: nothing was started or exec'd to stand in for it, so
        # its output is still the terminal's and Ctrl-C still reaches it
        self.assertEqual(seen["pid"], os.getpid())
        self.assertEqual(seen["state"]["pid"], os.getpid())
        self.assertEqual(seen["state"]["scope"], unit)
        self.assertEqual(seen["state"]["memory_cap_mb"], 512)
        self.assertEqual(self.niced, [10])
        self.assertTrue(host.cgroup_contains(f"/agentkit-test-runs.slice/{unit}.scope"))
        mib = str(512 * 1024 * 1024)
        self.assertEqual(self.called(), [[
            "busctl", "--user", "call", "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
            "org.freedesktop.systemd1.Manager", "StartTransientUnit", "ssa(sv)a(sa(sv))",
            f"{unit}.scope", "fail", "7", "PIDs", "au", "1", str(os.getpid()),
            "Slice", "s", "agentkit-test-runs.slice", "CPUWeight", "t", "40",
            "IOWeight", "t", "40", "MemoryMax", "t", mib, "MemorySwapMax", "t", mib,
            "OOMPolicy", "s", "continue", "0"]])
        self.assertEqual(self.scope_lines(seen["log"]), ["scope: pending", f"scope: {unit}"])
        self.assertIn(f"scope: {unit}", seen["out"])

        # the same run sent off with --bg: the same unit, slice and limits, as `-p` words
        placed = {}

        def start(argv, unit, env, output, **kwargs):
            placed.update(unit=unit, **kwargs)
            kwargs["placement"].update(scope=unit)
            return 99999901

        directory = seen["run_dir"]
        record.save_state(directory, {**record.read_state(directory), "scope": None})
        with patch.object(orch, "start_in_slice", side_effect=start), \
                redirect_stdout(io.StringIO()):
            run.spawn_bg(directory, [str(self.task)])
        self.assertEqual((placed["unit"], placed["target_slice"]),
                         (unit, "agentkit-test-runs.slice"))
        self.assertEqual(placed["properties"], (
            "-p", "CPUWeight=40", "-p", "IOWeight=40", "-p", "MemoryMax=512M",
            "-p", "MemorySwapMax=512M", "-p", "OOMPolicy=continue"))

    def test_where_no_scope_can_be_made_the_run_goes_on_and_says_why(self):
        cases = (
            ("a Mac", False, None, None, "no user systemd manager"),
            ("a login shell", True, f"0::/user.slice/user-{os.getuid()}.slice/session-4.scope\n",
             None, "started outside the user manager, which cannot move it"),
            ("a refusal", True, None, "Unit agentkit-run-acme.scope already exists.",
             "busctl failed (Unit agentkit-run-acme.scope already exists.)"))
        for name, manager, cgroup, refuse, reason in cases:
            with self.subTest(name), patch.dict(os.environ, {"FAKE_REFUSE": refuse or ""}):
                self.own.write_text(cgroup or SEAT)
                self.calls.unlink(missing_ok=True)
                self.niced.clear()
                seen = self.launch(manager)
                self.assertEqual(seen["pid"], os.getpid())
                self.assertEqual((seen["state"]["scope"], seen["state"]["scope_reason"]),
                                 ("none", reason))
                self.assertNotIn("memory_cap_mb", seen["state"])
                self.assertEqual(self.niced, [])
                self.assertEqual(self.scope_lines(seen["log"]),
                                 ["scope: pending", f"scope: none ({reason})"])
                self.assertEqual([call[0] for call in self.called()],
                                 ["busctl"] if refuse else [])

    def test_a_move_that_happened_stays_recorded_whatever_failed_after_it(self):
        # the manager took the request and lost the reply; then the renice is refused
        for name, lost, renice in (("a lost reply", "1", None),
                                   ("a refused renice", "", PermissionError("denied"))):
            with self.subTest(name), patch.dict(os.environ, {"FAKE_LOST": lost}):
                self.own.write_text(SEAT)
                self.niced.clear()
                self.renice = renice
                seen = self.launch()
                unit = f"agentkit-run-{seen['run_dir'].name}"
                self.assertEqual((seen["state"]["scope"], seen["state"]["memory_cap_mb"]),
                                 (unit, 512))
                self.assertEqual(self.niced, [10])
                self.assertEqual(self.scope_lines(seen["log"])[-1], f"scope: {unit}")

    def test_a_move_queued_before_busctl_failed_is_waited_for(self):
        # The queued move lands just after this process first reads its old cgroup.
        queued, contains = Path(f"{self.own}.queued"), host.cgroup_contains

        def cgroup_contains(name, pid="self"):
            answer = contains(name, pid)
            if queued.exists() and name == f"/{queued.read_text()}":
                self.own.write_text(f"0::{USER}/agentkit-test-runs.slice/{queued.read_text()}\n")
                queued.unlink()
            return answer

        for mode in ("reply-error", "timeout"):
            with self.subTest(mode), patch.dict(os.environ, {"FAKE_QUEUE": mode}), \
                    patch.object(host, "cgroup_contains", side_effect=cgroup_contains):
                self.own.write_text(SEAT)
                seen = self.launch()
                unit = f"agentkit-run-{seen['run_dir'].name}"
                self.assertTrue(contains(f"/{unit}.scope"))
                self.assertEqual((seen["state"]["scope"], seen["state"]["memory_cap_mb"]),
                                 (unit, 512))

    def resume(self, thread=False):
        """`ak run resume` of a run an earlier attempt placed; what the loop went on from."""
        directory = config.RUNS / "20261002-0900-fix-the-api"
        if not directory.exists():
            (self.root / "wt-fix-the-api").mkdir()
            directory.mkdir(parents=True)
            (directory / "task.md").write_text(self.task.read_text())
        (directory / "log.txt").write_text("")
        record.save_state(directory, {
            "run_id": directory.name, "state": "interrupted", "recovery_pending": True,
            "scratch": True, "worktree": str(self.root / "wt-fix-the-api"), "rounds": 3,
            "scope": f"agentkit-run-{directory.name}", "memory_cap_mb": 512})
        seen = {}

        def loop(_cfg, run_dir, _opts, _log, prior=None, **_kw):
            seen.update(pid=os.getpid(), prior=dict(prior))
            return 0

        with patch.object(orch, "user_manager", return_value=True), \
                patch.object(orch, "next_scope_unit", side_effect=lambda unit: f"{unit}-2"), \
                patch.object(run, "drive", side_effect=loop), redirect_stdout(io.StringIO()):
            if thread:
                # a job adopting one of its tasks' runs, in one of its worker threads
                worker = threading.Thread(target=run.main, args=(["resume", directory.name],))
                worker.start()
                worker.join(60)
            else:
                self.assertEqual(run.main(["resume", directory.name]), 0)
        seen["log"] = (directory / "log.txt").read_text()
        return directory, seen

    def test_a_foreground_resume_goes_on_in_a_scope_of_its_own(self):
        # an earlier attempt's scope may linger under the plain name, so the resume takes the
        # next one, and the loop goes on from a copy that names it rather than the last one
        directory, seen = self.resume()
        unit = f"agentkit-run-{directory.name}-2"
        self.assertEqual(seen["pid"], os.getpid())
        self.assertEqual((seen["prior"]["scope"], seen["prior"]["memory_cap_mb"]), (unit, 512))
        self.assertEqual(record.read_state(directory)["scope"], unit)
        self.assertEqual([call[8] for call in self.called()], [f"{unit}.scope"])
        self.assertEqual(self.scope_lines(seen["log"]), [f"scope: {unit}"])

    def test_a_process_that_is_not_the_run_alone_or_is_placed_already_stays(self):
        # a caller that only imported ak (a test), and a job's worker thread, whose process
        # every task of the job shares: neither is one run's to move
        with patch.object(sys, "argv", [__file__]):
            seen = self.launch()
        self.assertNotIn("scope", seen["state"])
        self.assertEqual(self.scope_lines(seen["log"]), ["scope: pending"])
        directory, seen = self.resume(thread=True)
        self.assertEqual(seen["prior"]["scope"], f"agentkit-run-{directory.name}")
        # a recovery the tick started in the scope its receipt names is where it belongs
        self.own.write_text(f"0::{USER}/agentkit.slice/agentkit-test.slice/"
                            f"agentkit-test-runs.slice/agentkit-run-{directory.name}.scope\n")
        directory, seen = self.resume()
        self.assertEqual(seen["prior"]["scope"], f"agentkit-run-{directory.name}")
        self.assertEqual(self.called(), [])
        self.assertEqual(self.niced, [])
        self.assertEqual(self.scope_lines(seen["log"]), [])

    def test_stopping_its_own_scope_keeps_its_exit_status_and_new_children_terminable(self):
        # The run's ending stops its scope with this process inside it.  The fake `systemctl`
        # sends the SIGTERM the manager would, and the process still exits with its own code.
        self.own.write_text(f"0::{USER}/agentkit-test-runs.slice/agentkit-run-acme.scope\n")
        stopper = self.root / "stopper"
        stopper.mkdir()
        sent = self.root / "sent"
        (stopper / "systemctl").write_text(
            "#!/usr/bin/env python3\nimport os, signal, sys\n"
            "os.kill(os.getppid(), signal.SIGTERM)\n"
            f"open({str(sent)!r}, 'w').write(' '.join(sys.argv[1:]))\n")
        (stopper / "systemctl").chmod(0o755)
        ending = (
            "import subprocess, sys, time\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(REPO)!r})\n"
            "from agentkit import host, orch\n"
            f"host.OWN_CGROUP = Path({str(self.own)!r})\n"
            "orch.user_manager = lambda: True\n"
            "orch.stop_scope('agentkit-run-acme', wait=False)\n"
            "deadline = time.monotonic() + 30\n"
            f"while not Path({str(sent)!r}).exists() and time.monotonic() < deadline:\n"
            "    time.sleep(0.01)\n"
            "time.sleep(0.2)\n"
            "child = subprocess.run([sys.executable, '-c', "
            "'import signal, sys; sys.exit(signal.getsignal(signal.SIGTERM) != signal.SIG_DFL)'], "
            "timeout=30)\n"
            "if child.returncode: sys.exit(1)\n"
            # Deliver a delayed stop after Python has cleared its callable handlers.
            "class Shutdown:\n"
            "    def __del__(self):\n"
            "        import os, signal\n"
            "        os.kill(os.getpid(), signal.SIGTERM)\n"
            "shutdown = Shutdown()\n"
            "sys.exit(int(sys.argv[1]))\n")
        for code in (0, 1, 3):
            with self.subTest(exit=code):
                sent.unlink(missing_ok=True)
                child = subprocess.run(
                    [sys.executable, "-c", ending, str(code)], capture_output=True, text=True,
                    timeout=60, env={**os.environ, "PATH": f"{stopper}:{os.environ['PATH']}"})
                self.assertEqual(child.returncode, code, child.stderr)
                self.assertEqual(sent.read_text(),
                                 "--user stop agentkit-run-acme.scope agentkit-run-acme.service --no-block")


if __name__ == "__main__":
    unittest.main(verbosity=2)
