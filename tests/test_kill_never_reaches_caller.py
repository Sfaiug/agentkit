"""A kill asked for from inside a run never targets that run.

`limited()` used to read AGENTKIT_RUN from the caller's own environment whenever a
child was given none, and the marker sweep then signalled every process carrying it --
including the executor and the loop hosting the test. An inherited marker is not a
target: only an environment handed to the child names a run, and the sweep never
returns or signals the caller or its ancestors.

The processes signalled here are fixtures this file started, under a marker no other
run carries. A signal aimed anywhere else is recorded and not delivered.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import worker


def fresh_id():
    """A marker no other run -- and no other test -- can be carrying."""
    return f"test-kill-caller-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def lineage(pid):
    """That pid and its ancestors, by the same /proc walk the sweep uses."""
    chain, seen = [], set()
    while pid and pid not in seen and pid > 0:
        seen.add(pid)
        chain.append(pid)
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            parent = int(fields[1])
        except (OSError, ValueError, IndexError):
            break
        if parent <= 0:
            break
        pid = parent
    return chain


def marked_env(run_id):
    """A copy of this environment whose run marker is `run_id` and nothing else."""
    env = {key: value for key, value in os.environ.items() if key != worker.RUN_MARKER}
    env[worker.RUN_MARKER] = run_id
    return env


# Runs under a parent whose initial environment carries the marker. `scan` only reads.
# `kill` sweeps, and delivers a signal only to the detached sleeper it started: any
# other pid is recorded and left alone, so a regression cannot reach the run above.
CALLER = r'''
import json, os, subprocess, sys, time
from pathlib import Path

repo, result_path, mode = sys.argv[1:4]
sys.path.insert(0, repo)
from agentkit import worker

def lineage(pid):
    chain, seen = [], set()
    while pid and pid not in seen and pid > 0:
        seen.add(pid)
        chain.append(pid)
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            parent = int(fields[1])
        except (OSError, ValueError, IndexError):
            break
        if parent <= 0:
            break
        pid = parent
    return chain

def carries(pid, run_id):
    try:
        env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return False
    return f"AGENTKIT_RUN={run_id}".encode() in env

run_id = os.environ["AGENTKIT_RUN"]
chain = lineage(os.getpid())
subprocess.Popen(
    ["setsid", "sleep", "100"], start_new_session=True,
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
deadline = time.monotonic() + 3
raw, outside = [], []
while time.monotonic() < deadline:
    raw = worker.marked_pids(run_id)
    outside = [pid for pid in raw if pid not in chain]
    if outside:
        break
    time.sleep(0.05)
report = {
    "found": raw,
    "outside": outside,
    "chain": chain,
    "carried": [pid for pid in chain if carries(pid, run_id)],
    "me": os.getpid(),
    "parent": os.getppid(),
    "parent_carries": carries(os.getppid(), run_id),
    "me_carries": carries(os.getpid(), run_id),
    "parent_alive": Path(f"/proc/{os.getppid()}").exists(),
}
if mode == "kill":
    allowed = set(outside)
    signalled = []
    real_kill = os.kill

    def spy(pid, sig):
        signalled.append(pid)
        if pid not in allowed:
            return None
        return real_kill(pid, sig)

    os.kill = spy
    report["returned"] = bool(worker.kill_marked(run_id, grace=0.4))
    report["signalled"] = signalled
    left = []
    for pid in outside:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            continue
        if state not in ("Z", "X"):
            left.append(pid)
    report["left"] = left
Path(result_path).write_text(json.dumps(report))
'''

PARENT = r'''
import subprocess, sys
raise SystemExit(subprocess.call([sys.executable, *sys.argv[1:]]))
'''


class KillNeverReachesCaller(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="kill-caller-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def reap_group(self, proc, run_id):
        """End a fixture session, then whatever detached child still carries its marker.

        The marker belongs to this test alone. The group is the session `start_new_session`
        gave the fixture, which is not the session running the test.
        """
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            proc.wait(timeout=3)
        except (subprocess.TimeoutExpired, OSError):
            pass
        worker.kill_marked(run_id, grace=0.3)

    @staticmethod
    def reap_one(proc):
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=3)
        except (subprocess.TimeoutExpired, OSError):
            pass

    def run_marked_child(self, mode):
        """A python caller whose parent was exec'd carrying this test's marker."""
        run_id = fresh_id()
        caller = self.root / f"caller-{mode}.py"
        parent = self.root / f"parent-{mode}.py"
        result = self.root / f"result-{mode}.json"
        caller.write_text(CALLER)
        parent.write_text(PARENT)
        env = marked_env(run_id)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.Popen(
            [sys.executable, str(parent), str(caller), str(REPO), str(result), mode],
            start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.addCleanup(self.reap_group, proc, run_id)
        try:
            out, err = proc.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            self.fail(f"{mode} caller hung")
        text = (err + out).decode(errors="replace")
        self.assertEqual(proc.returncode, 0, text)
        self.assertTrue(result.exists(), text)
        report = json.loads(result.read_text())
        self.assertEqual(report["parent"], proc.pid)
        return report

    def test_limited_on_a_markerless_child_resolves_no_run(self):
        # AGENTKIT_RUN is set on this process, and the child is given no environment.
        # A bystander already carrying that same marker has to survive: the timeout
        # ends the child's session and never resolves a run to sweep.
        run_id = fresh_id()
        protected = set(lineage(os.getpid()))
        protected_groups = set()
        for pid in protected:
            try:
                protected_groups.add(os.getpgid(pid))
            except OSError:
                pass
        bystander = subprocess.Popen(
            ["sleep", "100"], start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=marked_env(run_id))
        self.addCleanup(self.reap_one, bystander)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and bystander.pid not in worker.marked_pids(run_id):
            time.sleep(0.05)
        self.assertIn(bystander.pid, worker.marked_pids(run_id))
        children, groups, kills, swept = [], [], [], []
        real_popen, real_kill, real_killpg = subprocess.Popen, os.kill, os.killpg
        real_marked = worker.kill_marked

        def popen(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            children.append((proc, kwargs.get("env")))
            return proc

        def spy_kill(pid, sig):
            kills.append(pid)
            if pid in protected:
                return None
            return real_kill(pid, sig)

        def spy_killpg(group, sig):
            groups.append(group)
            if group in protected_groups:
                return None
            return real_killpg(group, sig)

        def spy_marked(rid, grace=worker.MARK_KILL_GRACE, log=None):
            swept.append(rid)
            return real_marked(rid, grace=grace, log=log)

        with patch.dict(os.environ, {worker.RUN_MARKER: run_id}), \
                patch.object(subprocess, "Popen", popen), \
                patch.object(os, "kill", spy_kill), \
                patch.object(os, "killpg", spy_killpg), \
                patch.object(worker, "kill_marked", spy_marked):
            self.assertEqual(os.environ.get(worker.RUN_MARKER), run_id)
            code, _, killed = worker.limited(
                ["sleep", "30"], 0.5, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertEqual(code, worker.TIMEOUT)
        self.assertTrue(killed)
        self.assertEqual([env for _, env in children], [None])
        child = children[0][0]
        self.assertEqual(swept, [])
        self.assertEqual(kills, [])
        self.assertTrue(groups)
        self.assertEqual(set(groups), {child.pid})
        self.assertNotIn(os.getppid(), kills)
        self.assertTrue(Path(f"/proc/{bystander.pid}").exists())
        try:
            os.kill(bystander.pid, 0)
        except OSError:
            self.fail("the marker sweep took the bystander")

    def test_a_copied_caller_marker_is_not_a_sweep_target(self):
        # An env dict that still holds this process's own AGENTKIT_RUN is the inherited
        # marker, not a run handed to the child.  A bystander carrying it must survive
        # the timeout; only the child's session is signalled.
        run_id = fresh_id()
        protected = set(lineage(os.getpid()))
        protected_groups = set()
        for pid in protected:
            try:
                protected_groups.add(os.getpgid(pid))
            except OSError:
                pass
        bystander = subprocess.Popen(
            ["sleep", "100"], start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=marked_env(run_id))
        self.addCleanup(self.reap_one, bystander)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and bystander.pid not in worker.marked_pids(run_id):
            time.sleep(0.05)
        self.assertIn(bystander.pid, worker.marked_pids(run_id))
        children, groups, kills, swept = [], [], [], []
        real_popen, real_kill, real_killpg = subprocess.Popen, os.kill, os.killpg
        real_marked = worker.kill_marked

        def popen(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            children.append(proc)
            return proc

        def spy_kill(pid, sig):
            kills.append(pid)
            if pid in protected:
                return None
            return real_kill(pid, sig)

        def spy_killpg(group, sig):
            groups.append(group)
            if group in protected_groups:
                return None
            return real_killpg(group, sig)

        def spy_marked(rid, grace=worker.MARK_KILL_GRACE, log=None):
            swept.append(rid)
            return real_marked(rid, grace=grace, log=log)

        copied = marked_env(run_id)
        with patch.dict(os.environ, {worker.RUN_MARKER: run_id}), \
                patch.object(subprocess, "Popen", popen), \
                patch.object(os, "kill", spy_kill), \
                patch.object(os, "killpg", spy_killpg), \
                patch.object(worker, "kill_marked", spy_marked):
            code, _, killed = worker.limited(
                ["sleep", "30"], 0.5, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=copied)
        self.assertEqual(code, worker.TIMEOUT)
        self.assertTrue(killed)
        self.assertEqual(swept, [])
        self.assertEqual(kills, [])
        self.assertEqual(set(groups), {children[0].pid})
        self.assertTrue(Path(f"/proc/{bystander.pid}").exists())

    def test_marked_pids_skips_caller_and_ancestors_carrying_the_id(self):
        # The caller and the parent it was exec'd under both carry the id in /proc.
        # The scan still returns the detached sleeper, and neither of them.
        report = self.run_marked_child("scan")
        self.assertTrue(report["me_carries"])
        self.assertTrue(report["parent_carries"])
        self.assertIn(report["me"], report["carried"])
        self.assertIn(report["parent"], report["carried"])
        self.assertTrue(report["outside"])
        self.assertFalse(set(report["found"]) & set(report["chain"]))
        self.assertFalse(set(report["found"]) & set(report["carried"]))

    def test_kill_marked_with_the_callers_run_id_spares_the_parent(self):
        # kill_marked(the id this caller itself carries) returns, ends the detached
        # sleeper, and never signals the parent that carries the same id.
        report = self.run_marked_child("kill")
        self.assertTrue(report["parent_carries"])
        self.assertTrue(report["me_carries"])
        self.assertTrue(report["parent_alive"])
        self.assertTrue(report["returned"])
        self.assertEqual(report["left"], [])
        self.assertTrue(report["signalled"])
        self.assertNotIn(report["parent"], report["signalled"])
        self.assertNotIn(report["me"], report["signalled"])
        self.assertTrue(set(report["signalled"]) <= set(report["outside"]))

    def test_explicit_child_env_names_the_run_and_ends_marked_processes(self):
        # An environment handed to the child still names the run: a setsid sleeper
        # carrying that marker dies with the killed turn, and the caller's ancestors
        # are not signalled on the way.
        run_id = fresh_id()
        protected = set(lineage(os.getpid()))
        kills, swept = [], []
        real_kill, real_marked = os.kill, worker.kill_marked

        def spy_kill(pid, sig):
            kills.append(pid)
            if pid in protected:
                return None
            return real_kill(pid, sig)

        def spy_marked(rid, grace=worker.MARK_KILL_GRACE, log=None):
            swept.append(rid)
            return real_marked(rid, grace=grace, log=log)

        seen, stop = [], threading.Event()

        def watch():
            while not stop.is_set():
                seen.extend(worker.marked_pids(run_id))
                time.sleep(0.05)

        watcher = threading.Thread(target=watch)
        watcher.start()
        self.addCleanup(worker.kill_marked, run_id, 0.3)
        try:
            with patch.object(os, "kill", spy_kill), \
                    patch.object(worker, "kill_marked", spy_marked):
                code, _, killed = worker.limited(
                    ["bash", "-c",
                     "setsid sleep 100 </dev/null >/dev/null 2>&1 & exec sleep 30"],
                    2, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, env=marked_env(run_id))
        finally:
            stop.set()
            watcher.join()
        self.assertEqual(code, worker.TIMEOUT)
        self.assertTrue(killed)
        self.assertIn(run_id, swept)
        self.assertTrue(seen, "the detached child was never observed mid-turn")
        self.assertEqual(worker.marked_pids(run_id), [])
        self.assertFalse(set(kills) & protected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
