"""Live checks belong to ak's slice, from cron and after a harness upgrade.

Offline: fake systemd-run and git execute only this test's tiny live script; systemctl
records stops, and no real manager, checkout, harness or live suite is reached.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

from fixtures.sandbox import Sandbox
from agentkit import config, host, orch, update, worker

POPEN, NOW = subprocess.Popen, time.time
TIP = "a" * 40
SYSTEMD = '''#!{python}
import json, os, sys
args = sys.argv[1:]
scoped = "--scope" in args
with open(os.environ["AK_LIVE_UNITS"], "a") as out:
    out.write(json.dumps([os.path.basename(sys.argv[0]), *args]) + "\\n")
if os.path.basename(sys.argv[0]) == "systemctl":
    sys.exit(int(os.environ.get("AK_LIVE_STOP_CODE", "0")))
if os.environ.get("AK_LIVE_REFUSE") and ("--wait" in args or "--pipe" in args):
    sys.stderr.write("Failed to connect to user scope bus via local transport: No such file or directory\\n")
    sys.exit(1)
env = dict(os.environ)
while args and args[0].startswith("-"):
    arg = args.pop(0)
    if arg == "--":
        break
    if arg == "-p":
        arg = "--property=" + args.pop(0)
    if arg.startswith("--setenv="):
        key, value = arg[len("--setenv="):].split("=", 1)
        env[key] = value
    if arg.startswith("--slice="):
        env["AK_LIVE_SLICE"] = arg.split("=", 1)[1]
    if arg.startswith("--property=WorkingDirectory="):
        os.chdir(arg.split("=", 2)[2])
    if arg.startswith("--property=StandardOutput=append:"):
        with open(arg.split("append:", 1)[1], "a") as out:
            os.dup2(out.fileno(), 1)
            os.dup2(out.fileno(), 2)
if not scoped:
    args = [arg.replace("$$", "$") for arg in args]
os.execvpe(args[0], args, env)
'''
GIT = '''#!{python}
import pathlib, shutil, sys
repo = pathlib.Path(sys.argv[2])
if sys.argv[4] == "add":
    shutil.copytree(repo / "tests", pathlib.Path(sys.argv[-2]) / "tests")
else:
    shutil.rmtree(sys.argv[-1])
'''


class LiveCheckInSlice(Sandbox):
    def setUp(self):
        super().setUp()
        self.manager = True
        self.stack.enter_context(patch.object(orch, "user_manager", lambda: self.manager))
        own = self.root / "cgroup"
        own.write_text("0::/system.slice/cron.service\n")
        self.stack.enter_context(patch.object(host, "OWN_CGROUP", own))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, script in (("systemd-run", SYSTEMD), ("systemctl", SYSTEMD), ("git", GIT)):
            path = self.bin / name
            path.write_text(script.format(python=sys.executable))
            path.chmod(0o755)
        self.units = self.root / "units"
        self.stack.enter_context(patch.dict(os.environ, {
            "PATH": f"{self.bin}:{os.environ['PATH']}", "AK_LIVE_UNITS": str(self.units)}))
        self.repo = self.root / "acme"
        tests = self.repo / "tests"
        tests.mkdir(parents=True)
        (tests / "smoke.sh").write_text("exit 0\n")
        probe = ('import json, os; print(json.dumps(dict('
                 'slice=os.environ.get("AK_LIVE_SLICE"), cwd=os.getcwd(), '
                 'required=os.environ.get("AGENTKIT_ACCEPTANCE_REQUIRED"), '
                 f'marker=os.environ.get({worker.RUN_MARKER!r}), '
                 'pin=os.environ.get("DISABLE_AUTOUPDATER"))))')
        self.live = tests / "live.sh"
        self.live.write_text(f"{shlex.quote(sys.executable)} -c {shlex.quote(probe)}\n")
        self.stack.enter_context(patch.object(config, "REPO", self.repo))
        self.stack.enter_context(patch.object(update, "agentkit_dir", return_value=self.repo))
        self.stack.enter_context(patch.object(update.gitcall, "no_auto_gc"))
        self.children = []
        self.stack.enter_context(patch.object(subprocess, "Popen", side_effect=self.spawn))
        self.addCleanup(self.reap)

    def spawn(self, argv, **kwargs):
        proc = POPEN(argv, **kwargs)
        self.children.append(proc)
        return proc

    def reap(self):
        for proc in self.children:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                self.fail(f"test child did not finish: {proc.args}")

    def commands(self):
        return [json.loads(line) for line in self.units.read_text().splitlines()] \
            if self.units.exists() else []

    def tick(self):
        def git(*args):
            return (1, "") if args[0] == "merge-base" else (0, TIP)

        with patch.object(update, "_git", side_effect=git):
            update.live_tick(lambda _: None, NOW(), fetched=True)
        self.reap()
        _, _, check = update.live_checks()[0]
        self.assertEqual((check / "exit").read_text(), "0\n")
        result = json.loads((check / "output").read_text().splitlines()[0])
        self.assertEqual(result["cwd"], str(check / "tree"))
        self.assertEqual(result["marker"], str(check))
        self.assertEqual((result["required"], result["pin"]), ("1", "1"))
        return result

    def test_new_code_check_starts_in_slice_from_cron(self):
        self.assertFalse(orch.can_scope())
        self.assertEqual(self.tick()["slice"], orch.slice_name())
        command, = self.commands()
        self.assertIn(f"--slice={orch.slice_name()}", command)
        self.assertNotIn("--scope", command)

    def test_new_code_check_starts_plainly_without_manager(self):
        self.manager = False
        self.assertIsNone(self.tick()["slice"])
        self.assertEqual(self.commands(), [])
        self.assertEqual(self.children[0].args[0], sys.executable)

    def upgrade(self, code=0):
        self.live.write_text(self.live.read_text() + f"exit {code}\n")
        harness = {"name": "acme", "upgrade": [sys.executable, "-c", ""], "env": {}}
        with patch.object(update, "version", return_value="2.0.0"), \
                patch.object(update, "fresh_gate", return_value=(True, "passed")), \
                patch.object(update, "revert", return_value={}) as revert, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(update.upgrade([harness], {"acme": "1.0.0"}), bool(code))
        self.assertEqual(revert.called, bool(code))
        log, = config.TMP.glob("update-*.log")
        result, = [json.loads(line) for line in log.read_text().splitlines()
                   if line.startswith('{"slice":')]
        self.assertEqual((result["required"], result["pin"]), ("1", "1"))
        self.assertEqual(result["cwd"], str(Path.cwd()))
        return result

    def test_harness_check_waits_in_slice_and_its_failure_reverts(self):
        self.assertEqual(self.upgrade(code=7)["slice"], orch.slice_name())
        start, stop = self.commands()
        self.assertIn("--wait", start)
        self.assertIn(f"--slice={orch.slice_name()}", start)
        unit = next(arg.removeprefix("--unit=") for arg in start if arg.startswith("--unit="))
        self.assertEqual(stop, ["systemctl", "--user", "stop", f"{unit}.service"])

    def test_harness_check_starts_plainly_without_manager(self):
        self.manager = False
        self.assertIsNone(self.upgrade()["slice"])
        self.assertEqual(self.commands(), [])

    def test_harness_check_from_user_manager_uses_a_scope(self):
        with patch.object(orch, "can_scope", return_value=True), \
                patch.object(orch, "scope_ends", return_value=""):
            self.assertEqual(self.upgrade(code=7)["slice"], orch.slice_name())
        start, stop = self.commands()
        self.assertIn("--scope", start)
        self.assertTrue(stop[-1].endswith(".scope"))

    def test_harness_check_starts_plainly_when_placement_is_refused(self):
        with patch.dict(os.environ, {"AK_LIVE_REFUSE": "1", "AK_LIVE_STOP_CODE": "5"}):
            self.assertIsNone(self.upgrade()["slice"])
        start, = self.commands()
        self.assertIn("--wait", start)

    def test_harness_check_starts_plainly_when_launcher_is_missing(self):
        def spawn(argv, **kwargs):
            if argv[0] == "systemd-run":
                raise FileNotFoundError("fixture: systemd-run disappeared")
            return self.spawn(argv, **kwargs)

        with patch.object(subprocess, "Popen", side_effect=spawn):
            self.assertIsNone(self.upgrade()["slice"])

    def test_a_timed_out_harness_check_stops_its_service(self):
        proc = Mock(pid=4242, returncode=None)
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired("fixture", 1), 0]
        with (config.TMP / "timeout.log").open("w") as out, \
                patch.object(subprocess, "Popen", return_value=proc), \
                patch.object(orch, "marked_pid", return_value=4242), \
                patch.object(orch.os, "killpg") as kill, \
                patch.object(orch, "stop_scope") as stop, \
                redirect_stdout(io.StringIO()):
            self.assertFalse(update.step(["bash", str(self.live)], out,
                                         target_slice=orch.slice_name()))
        kill.assert_called_once()
        stop.assert_called_once()
        self.assertTrue(stop.call_args.args[0].endswith(".service"))

    def test_foreground_work_respects_an_unresolved_launch_claim(self):
        unit = "agentkit-update-held"
        claim = config.TMP / f"{unit}.placed"
        claim.write_text(f"{unit}.service")
        with (config.TMP / "claim.log").open("w") as out, \
                patch.object(orch, "unit_loaded", return_value=True):
            with self.assertRaises(OSError):
                orch.call_in_slice([sys.executable, "-c", ""], unit, config.child_env(), out,
                                   target_slice=orch.slice_name())
        self.assertEqual(self.children, [])
        self.assertTrue(claim.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
