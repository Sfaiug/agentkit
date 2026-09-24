"""A run's memory cap is its own, and a seat is never throttled with its runs.

The unit tests inject every kill and every systemctl.  Nothing here signals a
pid, a process group, or an `agentkit-run-*` unit.  The one integration test
starts a throwaway scope under `agentkit-test-cap*`, inside `agentkit-test.slice`,
and only after the child has seen a memory.max of at most 64 MB in that scope.
It never calls os.kill, killpg or pkill.  The kernel's own cap is what ends the
allocator; the only systemctl stop is that throwaway scope, and only under a
name this test minted.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run, worker


# The allocator refuses to touch a page unless its own cgroup is the throwaway
# slice and memory.max is a small number.  A scope that did not take the cap
# exits before allocating, so a missed property cannot leak into this run.
ALLOCATOR = r"""
import sys, time
from pathlib import Path
needle, seat, status_path = sys.argv[1], sys.argv[2], Path(sys.argv[3])
lines = Path("/proc/self/cgroup").read_text().splitlines()
cg = next(line.split("::", 1)[1] for line in lines if line.startswith("0::"))
if needle not in cg or seat in cg:
    status_path.write_text("refused " + cg + "\n")
    raise SystemExit(3)
root = Path("/sys/fs/cgroup") / cg.lstrip("/")
text = (root / "memory.max").read_text().strip()
swap = (root / "memory.swap.max").read_text().strip()
if text == "max" or swap == "max":
    status_path.write_text(f"refused {text} {swap}\n")
    raise SystemExit(3)
limit, swap_limit = int(text), int(swap)
if limit > 64 * 1024 * 1024 or swap_limit > 64 * 1024 * 1024:
    status_path.write_text(f"refused {text} {swap}\n")
    raise SystemExit(3)
status_path.write_text("armed " + cg + "\n")
# RAM and swap are capped separately, so the process can sit on both before
# the kernel kills it.  Hold past the sum and do not exit: a process that
# returns the moment it crosses the line can win the race against the killer.
chunks = []
block = 256 * 1024
used = 0
target = limit + swap_limit + 8 * 1024 * 1024
deadline = time.monotonic() + 20
while used < target and time.monotonic() < deadline:
    blob = bytearray(block)
    for offset in range(0, block, 4096):
        blob[offset] = 1
    chunks.append(blob)
    used += block
while time.monotonic() < deadline:
    time.sleep(0.05)
status_path.write_text(f"survived {text} {swap} {used}\n")
raise SystemExit(0)
"""


SPY = """#!{python}
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with pathlib.Path(os.environ["AK_SLICE_LOG"]).open("a") as fh:
    fh.write(json.dumps([name, *sys.argv[1:]]) + "\\n")
if name == "systemctl" and sys.argv[1:3] == ["--user", "is-system-running"]:
    print("running")
elif name == "systemctl" and sys.argv[1:2] == ["show"]:
    print(os.environ.get("AK_SLICE_USER_TASKS", "8192"))
elif name == "nproc":
    print(os.environ.get("AK_SLICE_CPUS", "4"))
raise SystemExit(0)
"""


def _fields(text):
    found = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            found[key.strip()] = value.strip()
    return found


def _show(unit):
    proc = subprocess.run(
        ["systemctl", "--user", "show", unit, "-p", "Result", "-p", "ActiveState",
         "-p", "LoadState", "-p", "ControlGroup"],
        capture_output=True, text=True, timeout=5,
        stdin=subprocess.DEVNULL)
    return _fields(proc.stdout)


def _pressure_avg10(text):
    for line in text.splitlines():
        if line.startswith("some "):
            for part in line.split():
                if part.startswith("avg10="):
                    return float(part.split("=", 1)[1])
    return None


class MemoryCap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ak-memory-cap-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()
        # No test signals a marked pid.  The scope stop stays real only for the
        # integration test, which wraps it and checks the unit name first.
        # Every other test injects the stop.
        self.stopped = []
        self.stack.enter_context(patch.object(worker, "kill_marked", return_value=True))

    def reaped(self, directory, probe):
        with patch.object(
                orch, "stop_scope",
                side_effect=lambda scope, log=None, wait=True: self.stopped.append(scope) or True):
            return run.reap(directory, run.read_state(directory), memory_probe=probe)

    def run_dir(self, name, **extra):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        run.save_state(directory, {
            "run_id": name, "title": "a leaking executor", "state": "running",
            "verdict": None, "scope": f"agentkit-test-cap-{name}",
            "memory_cap_mb": 4096, **extra})
        return directory

    def test_the_cap_ends_the_run_with_the_reason(self):
        directory = self.run_dir("oom")
        state = self.reaped(directory, lambda _state: ("oom-kill", 0))
        self.assertEqual(state["state"], "fail")
        self.assertEqual(state["verdict"], "FAIL")
        self.assertEqual(state["error"], "killed: memory cap 4 GB")
        self.assertIn("killed: memory cap 4 GB", (directory / "log.txt").read_text())
        self.assertEqual(self.stopped, ["agentkit-test-cap-oom"])
        # The cgroup count is the other witness, for a Result that was already collected.
        counted = self.run_dir("counted")
        self.stopped.clear()
        state = self.reaped(counted, lambda _state: ("", 2))
        self.assertEqual(state["state"], "fail")
        self.assertEqual(state["error"], "killed: memory cap 4 GB")

    def test_a_plain_death_stays_an_interruption(self):
        directory = self.run_dir("plain")
        state = self.reaped(directory, lambda _state: ("success", 0))
        self.assertEqual(state["state"], "interrupted")
        self.assertNotIn("memory cap", state.get("interruption_reason", ""))
        log = directory / "log.txt"
        self.assertFalse(log.exists() and "memory cap" in log.read_text())
        # No cap was recorded, so the reaper must not go looking for one.
        bare = self.run_dir("bare", memory_cap_mb=None)
        run.save_state(bare, {**run.read_state(bare), "memory_cap_mb": None})
        state = run.read_state(bare)
        state.pop("memory_cap_mb", None)
        run.save_state(bare, state)

        def explode(_state):
            raise AssertionError("a run with no cap was probed")

        state = self.reaped(bare, explode)
        self.assertEqual(state["state"], "interrupted")

    def test_the_reason_reaches_result_and_the_handback(self):
        directory = self.run_dir("handed")
        state = self.reaped(directory, lambda _state: ("oom-kill", 1))
        result = (directory / "result.md").read_text()
        self.assertIn("killed: memory cap 4 GB", result)
        self.assertIn("## Why this run stopped", result)
        line = run.handback_line(state, directory)
        self.assertIn("finished FAIL: killed: memory cap 4 GB.", line)
        self.assertIn(str(directory / "result.md"), line)
        self.assertNotIn("rounds", run.handback_reason(state))

    def test_the_config_key_changes_the_cap(self):
        # No key: the smaller of 4 GB and 40% of the ceiling handed in.
        self.assertIsNone(config.run_memory_max_mb())
        self.assertEqual(run.memory_cap_mb(20000), 4096)
        self.assertEqual(run.memory_cap_mb(5000), 2000)
        self.assertEqual(run.memory_cap_line(4096), "killed: memory cap 4 GB")
        self.assertEqual(run.memory_cap_line(512), "killed: memory cap 0.5 GB")
        drop = self.root / ".config/systemd/user/agentkit-test.slice.d"
        drop.mkdir(parents=True)
        (drop / "limits.conf").write_text("[Slice]\nMemoryMax=5000M\n")
        self.assertEqual(orch.slice_memory_max_mb(), 5000)
        self.assertEqual(run.memory_cap_mb(), 2000)
        (drop / "limits.conf").write_text("[Slice]\nMemoryMax=50%\n")
        self.assertEqual(orch.slice_memory_max_mb(mem_total_mb=10000), 5000)
        # The key replaces the formula, ceiling included.
        (config.HOME / "config.toml").write_text("run_memory_max_mb = 512\n")
        self.assertEqual(config.run_memory_max_mb(), 512)
        self.assertEqual(run.memory_cap_mb(20000), 512)
        cap, props = run.run_scope_limits()
        self.assertEqual(cap, 512)
        self.assertIn("MemoryMax=512M", props)
        self.assertIn("MemorySwapMax=512M", props)
        directory = config.RUNS / "20260922-0900-capped"
        directory.mkdir()
        run.save_state(directory, {"run_id": directory.name, "state": "queued"})
        seen = {}

        def placed(*args, **kwargs):
            seen["properties"] = kwargs["properties"]
            seen["slice"] = kwargs["target_slice"]
            kwargs["placement"].update(scope="agentkit-test-run-capped")
            return 4242

        with patch.object(run, "process_owner",
                          return_value={"pid": 4242, "process_identity": None}), \
                patch.object(orch, "start_in_slice", side_effect=placed), \
                redirect_stdout(io.StringIO()):
            run.spawn_bg(directory, ["resume", directory.name])
        self.assertEqual(seen["slice"], "agentkit-test-runs.slice")
        self.assertIn("MemoryMax=512M", seen["properties"])
        self.assertIn("MemorySwapMax=512M", seen["properties"])
        self.assertEqual(run.read_state(directory)["memory_cap_mb"], 512)
        (config.HOME / "config.toml").write_text("run_memory_max_mb = 0\n")
        with self.assertRaises(config.Error):
            config.run_memory_max_mb()

    def test_each_task_of_a_job_has_a_cap_of_its_own_and_meets_it_alone(self):
        # A job in its own scope, two of its tasks: each goes under its own cap, and the one
        # past it fails with the reason while its sibling carries on.  A fake process table and
        # placement: no pid is signalled and no unit is started or stopped.
        (config.HOME / "config.toml").write_text("run_memory_max_mb = 512\n")
        cgroup = self.root / "cgroup"
        cgroup.write_text("0::/user.slice/user@1000.service/agentkit-test.slice/"
                          "agentkit-test-runs.slice/agentkit-job-20260923-2000-job.scope\n")
        job = {"job_id": "20260923-2000-job", "scope": "agentkit-job-20260923-2000-job"}
        leaking, steady = "20260923-2000-leaking", "20260923-2000-steady"
        live, placed = {}, []

        def place(argv, unit, env, output, log=None, **kwargs):
            kwargs["placement"].update(scope=unit)
            placed.append((unit, kwargs["properties"]))
            live[99999900 + len(placed)] = Path(output).parent
            return 99999900 + len(placed)

        def finish(_seconds):
            # the kernel ends the leaking task at its cap; the steady one ends on its own
            for pid, directory in list(live.items()):
                if directory.name == steady:
                    run.save_state(directory, {**run.read_state(directory),
                                               "state": "pass", "verdict": "PASS"})
                del live[pid]

        boxes = {}
        with patch.object(orch, "OWN_CGROUP", cgroup), \
                patch.object(orch, "start_in_slice", side_effect=place), \
                patch.object(orch, "stop_scope", side_effect=lambda scope, log=None, wait=False:
                             self.stopped.append((scope, wait)) or True), \
                patch.object(run, "process_active", side_effect=lambda s: s.get("pid") in live), \
                patch.object(run, "_scope_oom_probe", side_effect=lambda s: (
                    ("oom-kill", 1) if s.get("scope") == f"agentkit-run-{leaking}"
                    else ("success", 0))), \
                patch.object(run.time, "sleep", side_effect=finish), \
                redirect_stdout(io.StringIO()):
            self.assertTrue(run.job_scoped(job))
            for name in (leaking, steady):
                directory = config.RUNS / name
                directory.mkdir()
                (directory / "task.md").write_text("---\nrepo: none\n---\n# A job task\n")
                run.save_state(directory, {"run_id": name, "state": "running",
                                           "slot_waiting": False, "job_id": job["job_id"],
                                           "pid": os.getpid()})
                boxes[name] = {}
                run.job_drive(config.load(), directory, {"--no-merge": True}, boxes[name],
                              run.job_scoped(job))
        self.assertEqual([unit for unit, _ in placed],
                         [f"agentkit-run-{leaking}", f"agentkit-run-{steady}"])
        for _unit, properties in placed:
            self.assertIn("MemoryMax=512M", properties)
            self.assertIn("MemorySwapMax=512M", properties)
        self.assertEqual(boxes[leaking]["state"]["state"], "fail")
        self.assertEqual(boxes[leaking]["state"]["error"], "killed: memory cap 0.5 GB")
        self.assertIn("killed: memory cap 0.5 GB",
                      (config.RUNS / leaking / "log.txt").read_text())
        self.assertEqual(boxes[steady]["state"]["state"], "pass")
        # the capped scope was stopped and waited on; the job's own scope never was
        self.assertIn((f"agentkit-run-{leaking}", True), self.stopped)
        self.assertNotIn(job["scope"], [scope for scope, _ in self.stopped])

    def test_seats_and_runs_sit_in_separate_slices_with_the_weights(self):
        with patch.dict(os.environ, {"AGENTKIT_TMUX_SOCKET": "agentkit"}), \
                patch.object(orch, "user_manager", return_value=True), \
                patch.object(orch, "can_scope", return_value=True):
            self.assertEqual(orch.seat_slice_name(), "agentkit-seats.slice")
            self.assertEqual(orch.run_slice_name(), "agentkit-runs.slice")
            self.assertNotEqual(orch.seat_slice_name(), orch.run_slice_name())
            seat_argv, _env = orch.in_slice(["sleep", "1"], "agentkit-seat-demo")
            _cap, props = run.run_scope_limits(ceiling_mb=20000)
            run_argv, _env = orch.in_slice(
                ["sleep", "1"], "agentkit-run-demo",
                target_slice=orch.run_slice_name(), properties=props)
        self.assertIn("--slice=agentkit-seats.slice", seat_argv)
        self.assertNotIn("CPUWeight=40", seat_argv)
        self.assertNotIn("IOWeight=40", seat_argv)
        self.assertIn("--slice=agentkit-runs.slice", run_argv)
        joined = " ".join(run_argv)
        self.assertIn("CPUWeight=40", joined)
        self.assertIn("IOWeight=40", joined)
        self.assertIn("MemoryMax=4096M", joined)
        self.assertIn("MemorySwapMax=4096M", joined)
        # 40 is the runs' weight; the seats' drop-in is 100, checked with the installer.
        self.assertLess(40, 100)

    def test_the_installer_writes_both_dropins(self):
        source = (REPO / "install.sh").read_text()
        body = source[source.index("# --- (g3) the ceiling"):source.index("# --- (h) a new phone key")]
        home = self.root / "install-home"
        home.mkdir()
        bindir = self.root / "bin"
        bindir.mkdir()
        log = self.root / "commands.jsonl"
        for name in ("systemctl", "nproc"):
            path = bindir / name
            path.write_text(SPY.format(python=sys.executable))
            path.chmod(0o755)
        meminfo = self.root / "meminfo"
        meminfo.write_text("MemTotal:       16777216 kB\n")
        prelude = ("set -euo pipefail\n"
                   f"HOME={shlex.quote(str(home))}\nROLE=server\nSANDBOX=0\n"
                   "have() { command -v \"$1\" >/dev/null 2>&1; }\n"
                   "note() { echo \"note: $*\" >&2; }\n")
        result = subprocess.run(
            ["bash", "-c", prelude + body], capture_output=True, text=True, timeout=60,
            env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
                 "AK_SLICE_LOG": str(log), "AK_SLICE_USER_TASKS": "8192",
                 "AK_SLICE_CPUS": "4", "MEMINFO": str(meminfo),
                 "HOME": str(home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        seats = (home / ".config/systemd/user/agentkit-seats.slice.d/weights.conf").read_text()
        runs = (home / ".config/systemd/user/agentkit-runs.slice.d/weights.conf").read_text()
        self.assertIn("CPUWeight=100\nIOWeight=100\n", seats)
        self.assertIn("CPUWeight=40\nIOWeight=40\n", runs)
        self.assertGreater(
            int(seats.split("CPUWeight=")[1].splitlines()[0]),
            int(runs.split("CPUWeight=")[1].splitlines()[0]))
        self.assertGreater(
            int(seats.split("IOWeight=")[1].splitlines()[0]),
            int(runs.split("IOWeight=")[1].splitlines()[0]))
        # The fake systemctl is the only one the installer could reach, and it
        # was asked to reload, not to stop anything.
        commands = log.read_text()
        self.assertIn("daemon-reload", commands)
        self.assertNotIn("stop", commands)
        # The files were written under the HOME this test handed the script, a
        # directory of its own, not the account's.
        self.assertEqual(home.parent, self.root)
        self.assertTrue(str(home).startswith(str(self.root)))

    def test_unbounded_allocator_ends_fail_and_the_seat_slice_shows_no_pressure(self):
        if not shutil.which("systemd-run") or not orch.user_manager():
            self.skipTest("no user systemd manager")
        token = f"agentkit-test-cap{os.getpid() % 100000}{uuid.uuid4().hex[:4]}"
        self.assertTrue(token.startswith("agentkit-test-cap"))
        seat_slice = f"{token}-seats.slice"
        run_slice = f"{token}-runs.slice"
        seat_unit = f"{token}-seat"
        bomb_unit = f"{token}-bomb"
        for name in (seat_slice, run_slice, seat_unit, bomb_unit):
            self.assertNotIn(name, {
                "agentkit.slice", "agentkit-seats.slice", "agentkit-runs.slice",
                "agentkit-test.slice", "agentkit-test-runs.slice"})
        (config.HOME / "config.toml").write_text("run_memory_max_mb = 32\n")
        cap, props = run.run_scope_limits()
        self.assertEqual((cap, "MemoryMax=32M", "MemorySwapMax=32M"),
                         (32, ) + tuple(item for item in props if item.startswith("Memory")))
        status = self.root / "bomb-status"
        sleeper = subprocess.Popen(
            ["systemd-run", "--user", f"--slice={seat_slice}", "--scope", "--quiet",
             "--collect", f"--unit={seat_unit}", "--", "sleep", "8"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(sleeper.wait, timeout=15)

        def stop_bomb():
            # The scope and the throwaway slice that held it.  Both names were
            # minted above; neither is the owner's, and neither is agentkit-test.slice.
            unit = f"{bomb_unit}.scope"
            parent = f"{token}.slice"
            self.assertTrue(unit.startswith("agentkit-test-cap") and unit.endswith("-bomb.scope"))
            self.assertTrue(parent.startswith("agentkit-test-cap") and parent != "agentkit-test.slice")
            subprocess.run(
                ["systemctl", "--user", "stop", unit, parent],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=10)
            subprocess.run(
                ["systemctl", "--user", "reset-failed", unit],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=10)
        self.addCleanup(stop_bomb)

        seat_cg = ""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            shown = _show(f"{seat_unit}.scope")
            if shown.get("ActiveState") == "active" and shown.get("ControlGroup"):
                seat_cg = shown["ControlGroup"]
                break
            time.sleep(0.05)
        self.assertIn(seat_slice.removesuffix(".slice"), seat_cg)
        seat_dir = Path("/sys/fs/cgroup") / seat_cg.lstrip("/")
        slice_dir = seat_dir.parent
        self.assertTrue(slice_dir.name.startswith(token))
        self.assertTrue(slice_dir.name.endswith("-seats.slice"))
        before_current = int((slice_dir / "memory.current").read_text())
        before_pressure = _pressure_avg10((slice_dir / "memory.pressure").read_text())
        self.assertIsNotNone(before_pressure)
        try:
            subprocess.run(
                ["systemd-run", "--user", f"--slice={run_slice}", "--scope", "--quiet",
                 f"--unit={bomb_unit}", *props, "--",
                 sys.executable, "-c", ALLOCATOR, run_slice, seat_slice, str(status)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            self.fail("systemd-run did not return; the scope was not started")
        # systemd-run --scope may return once the scope exists, before the
        # kernel has killed it.  The status file is the child's own word that
        # it armed inside the cap; the unit Result is the kernel's.
        report = ""
        shown = {}
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if status.exists():
                report = status.read_text().strip()
            shown = _show(f"{bomb_unit}.scope")
            if report.startswith("armed") and shown.get("Result") == "oom-kill":
                break
            if report.startswith("refused") or report.startswith("survived"):
                break
            time.sleep(0.1)
        self.assertTrue(report.startswith("armed "), report or shown)
        self.assertIn(run_slice, report)
        self.assertNotIn(seat_slice, report.split(" ", 1)[1])
        self.assertEqual(shown.get("Result"), "oom-kill", shown)
        after_current = int((slice_dir / "memory.current").read_text())
        after_pressure = _pressure_avg10((slice_dir / "memory.pressure").read_text())
        self.assertLess(after_current - before_current, 8 * 1024 * 1024)
        self.assertLess(after_pressure, 1.0)
        self.assertLessEqual(after_pressure, before_pressure + 0.5)
        # The production reaper, against the real Result, stopping only this scope.
        directory = self.run_dir("live", scope=bomb_unit, memory_cap_mb=32)
        real_stop = orch.stop_scope

        def stop_only(scope, log=lambda _line: None, wait=True):
            self.assertEqual(scope, bomb_unit)
            self.stopped.append(scope)
            return real_stop(scope, log, wait=wait)

        with patch.object(orch, "stop_scope", side_effect=stop_only):
            state = run.reap(directory, run.read_state(directory))
        self.assertEqual(state["state"], "fail")
        self.assertEqual(state["error"], "killed: memory cap 0.03 GB")
        self.assertIn("killed: memory cap 0.03 GB", (directory / "log.txt").read_text())
        self.assertIn("killed: memory cap 0.03 GB", (directory / "result.md").read_text())
        self.assertIn("killed: memory cap 0.03 GB", run.handback_line(state, directory))
        self.assertIn(bomb_unit, self.stopped)
        self.assertNotEqual(_show(f"{bomb_unit}.scope").get("ActiveState"), "active")
        # Drop the throwaway slice (and the sleeper in it) once the readings
        # are taken, then reap the systemd-run client.  No signal from here.
        stop_bomb()
        sleeper.wait(timeout=15)


if __name__ == "__main__":
    unittest.main()
