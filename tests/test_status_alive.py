"""`ak run status` shows what is alive under each unfinished run; offline.

Fake run receipts under a throwaway HOME, fixture cgroup files for the scope
readings, and injected marker/rss callables for the fallback: the status
answers never signal a process, stop a unit, or read the real /proc. The only
child ever started is `tests/test_v4r.py` itself. It is killed only when it
overruns its timeout. The leak check gives that child a marker of its own and,
after it exits, reads /proc for processes still carrying the marker and for
processes still in that child's session. A pid is signalled only when it still
carries the marker, or it is that child and still this process's child, so a
failure cannot leave the fixture behind and cannot reach any other run.
"""

from contextlib import redirect_stdout
import io
import os
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
sys.path.insert(0, str(REPO))
from agentkit import config, run


def _cap_500mb():
    """The v4r child runs under a 500 MB address-space ceiling, so a leak that
    grows without bound dies on the ceiling instead of on the host."""
    import resource
    capped = 500 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (capped, capped))


def _left_behind(marker, leader):
    """(marked, children) still in /proc after the fixture run. Read-only.

    `marked` carries this test's own AGENTKIT_RUN. `children` still name the
    fixture as their parent or their process group: a session the fixture
    started, which nothing else is in.
    """
    want = f"AGENTKIT_RUN={marker}".encode()
    me = {os.getpid(), os.getppid(), leader}
    marked, children = [], []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return marked, children
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid in me:
            continue
        try:
            with open(f"/proc/{pid}/environ", "rb") as fh:
                env = fh.read()
        except OSError:
            env = b""
        if want in env.split(b"\0"):
            marked.append(pid)
        try:
            with open(f"/proc/{pid}/stat") as fh:
                fields = fh.read().rsplit(")", 1)[1].split()
            ppid, pgrp = int(fields[1]), int(fields[2])
        except (OSError, ValueError, IndexError):
            continue
        if ppid == leader or pgrp == leader:
            children.append(pid)
    return marked, children


def _end_fixture(marker, leader):
    """End the fixture child and anything still carrying its marker.

    A pid is signalled only when its environment still has the marker, or it
    is the leader and still this process's child. A recycled pid has neither,
    so the sweep cannot reach the run that asked or any other process.
    """
    want = f"AGENTKIT_RUN={marker}".encode()

    def ours(pid):
        if pid in (os.getpid(), os.getppid()):
            return False
        try:
            with open(f"/proc/{pid}/environ", "rb") as fh:
                if want in fh.read().split(b"\0"):
                    return True
        except OSError:
            pass
        if pid != leader:
            return False
        try:
            with open(f"/proc/{pid}/stat") as fh:
                fields = fh.read().rsplit(")", 1)[1].split()
            return int(fields[1]) == os.getpid()
        except (OSError, ValueError, IndexError):
            return False

    for sig in (signal.SIGTERM, signal.SIGKILL):
        marked, children = _left_behind(marker, leader)
        for pid in dict.fromkeys((leader, *marked, *children)):
            if not ours(pid):
                continue
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        if sig == signal.SIGTERM:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and _left_behind(marker, leader) != ([], []):
                time.sleep(0.05)


class StatusAlive(Sandbox):
    def receipt(self, name, **extra):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        state = {"run_id": name, "title": f"Run {name}", "executor": "opus",
                 "reviewer": "astra", "rounds": 3, "round_summaries": [{}],
                 "started_at": time.time() - 60, "reported": False, **extra}
        run.save_state(directory, state)
        return directory

    def status(self, argv):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_status(list(argv)), 0)
        return out.getvalue()

    def test_live_run_shows_process_count_and_memory(self):
        run_id = "20260922-0900-alive-scope"
        self.receipt(run_id, state="running", finished_at=None, pid=999999991,
                     process_identity=None, scope="test-alive-scope-r1")
        scope_dir = self.root / "scope-cgroup"
        scope_dir.mkdir()
        (scope_dir / "cgroup.procs").write_text("999999991\n999999992\n999999993\n")
        (scope_dir / "memory.current").write_text("1288490189\n")
        with patch.object(run, "run_scope_dir", return_value=scope_dir), \
                patch.object(run, "process_active", return_value=True):
            table = self.status([])
            alone = self.status([run_id])
        self.assertIn("3 processes · 1.2 GB", table)
        self.assertIn("3 processes · 1.2 GB", alone)

    def test_marker_scan_counts_where_there_is_no_scope(self):
        state = {"run_id": "20260922-0900-alive-plain", "state": "running",
                 "scope": "none", "pid": 999999994}
        marked = [999999995, 999999996]
        fifty = lambda pid: 50 * 1024 * 1024
        self.assertEqual(run.alive_line(state, _marker=lambda rid: marked,
                                        _rss=fifty, _active=lambda s: False),
                         "2 processes · 100 MB")
        # ... plus the loop itself while it is still the run's own.
        self.assertEqual(run.alive_line(state, _marker=lambda rid: marked,
                                        _rss=fifty, _active=lambda s: True),
                         "3 processes · 150 MB")

    def test_capped_run_dim_line_says_why(self):
        cases = {
            "20260922-0900-alive-capped": (
                {"state": "fail", "verdict": "FAIL",
                 "error": "killed: memory cap 4 GB",
                 "finished_at": time.time() - 10},
                "killed: memory cap 4 GB"),
            "20260922-0900-alive-stopped": (
                {"state": "stopped", "verdict": "STOPPED",
                 "error": "stopped by the user",
                 "finished_at": time.time() - 10},
                "stopped · stopped by the user"),
        }
        for run_id, (extra, reason) in cases.items():
            with self.subTest(run_id=run_id):
                self.receipt(run_id, scope="none", pid=999999999,
                             process_identity=None, **extra)
                text = self.status([run_id])
                self.assertIn(reason, text)
                self.assertNotIn("processes", text)
                self.assertNotIn("process ·", text)

    def test_finished_run_shows_neither_count_nor_reason(self):
        run_id = "20260922-0900-alive-done"
        directory = self.receipt(run_id, state="pass", verdict="PASS",
                                 merged=True, scope="none", pid=999999999,
                                 process_identity=None,
                                 finished_at=time.time() - 10)
        state = run.read_state(directory)
        self.assertEqual(run.alive_line(state), "")
        self.assertEqual(run.stop_note(state), "")
        text = self.status([run_id])
        self.assertNotIn("processes", text)
        self.assertNotIn("process ·", text)
        self.assertNotIn("stopped ·", text)

    def job(self, name, tasks, **extra):
        directory = config.JOBS / name
        directory.mkdir(parents=True)
        run.save_job(directory, {"job_id": name, "seat": None, "started_at": time.time() - 600,
                                 "finished_at": None, "tasks": tasks, "pid": 999999990,
                                 "process_identity": None, **extra})
        return directory

    def test_a_job_whose_launcher_is_gone_reports_its_runs_as_they_are(self):
        # both runs still read `running` on record: looking at the job reaps them
        for run_id in ("20260922-0900-job-first", "20260922-0901-job-second"):
            self.receipt(run_id, state="running", scope="none", pid=999999990,
                         process_identity=None)
        name = "20260922-090000-job-gone"
        self.job(name, [
            {"name": "a.md", "state": "running", "run_id": "20260922-0900-job-first"},
            {"name": "b.md", "state": "running", "run_id": "20260922-0901-job-second"},
            {"name": "c.md", "state": "waiting", "after": ["a.md"], "run_id": None}])
        # the launcher and both runs' loops are gone: nothing here is probed or signalled
        with patch.object(run, "process_active", return_value=False), \
                patch.object(run, "stop_run_tree"):
            alone = self.status([name])
            table = self.status([])
        for text in (table, alone):
            self.assertIn(f"job {name}: 1 waiting on a.md, 2 interrupted", text)
            self.assertNotIn("running", text)
            self.assertIn(f"launcher gone; ak run resume {name} to continue", text)
        self.assertIn("  a.md interrupted 20260922-0900-job-first  a.md: interrupted", alone)

    def test_a_job_task_reads_its_runs_current_ending(self):
        # resumed by hand after its job settled it as failed, and merged since: merged, though
        # its review is not one today's config would pass
        self.receipt("20260922-0902-job-merged", state="pass", verdict="PASS", merged=True,
                     round_summaries=[{}, {}, {}],
                     pr="https://github.com/o/r/pull/7", finished_at=time.time() - 60,
                     scope="none", pid=999999990, process_identity=None)
        # resumed too, and failed again a round later
        self.receipt("20260922-0903-job-failed", state="fail", verdict="FAIL",
                     round_summaries=[{}, {}, {}], finished_at=time.time() - 60, scope="none",
                     pid=999999990, process_identity=None)
        tasks = [{"name": "d.md", "state": "failed", "run_id": "20260922-0902-job-merged",
                  "verdict_line": "d.md: FAIL after 2 rounds: needs you"},
                 {"name": "e.md", "state": "failed", "run_id": "20260922-0903-job-failed",
                  "verdict_line": "e.md: FAIL after 2 rounds: needs you"}]
        # its line was handed back to the seat, or the seat was gone and the owner carded
        handed = self.job("20260922-090200-job-handed", tasks, finished_at=time.time() - 30,
                          card_sent={"kind": "handback", "at": time.time() - 30})
        carded = self.job("20260922-090300-job-carded", tasks, finished_at=time.time() - 20,
                          card_sent={"kind": "needs", "at": time.time() - 20})
        with patch.object(run, "process_active", return_value=False), \
                patch.object(run, "stop_run_tree"):
            table = self.status([])
        for job_dir in (handed, carded):
            self.assertIn(f"job {job_dir.name}: 1 merged, 1 failed", table)
        self.assertIn("  d.md: PASS, merged after 3 rounds https://github.com/o/r/pull/7", table)
        self.assertNotIn("d.md: FAIL", table)
        self.assertEqual(table.count("  e.md: FAIL after 3 rounds: needs you"), 1, table)
        self.assertEqual(table.count("  e.md: FAIL after 3 rounds\n"), 1, table)
        # the receipt keeps what the job wrote
        self.assertEqual(run.read_job(handed)["tasks"], tasks)

    def test_v4r_finishes_under_the_timeout(self):
        # The leak's own condition: stdin is a pipe that stays open and never
        # delivers EOF, the way a backgrounded run leaves it. The fixed test
        # never waits on stdin, so it finishes at once; the kill below can only
        # land on this test's own child, and only when it overruns.
        read_fd, write_fd = os.pipe()
        proc = subprocess.Popen(
            [sys.executable, str(REPO / "tests/test_v4r.py")],
            stdin=read_fd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=str(REPO), preexec_fn=_cap_500mb)
        os.close(read_fd)
        try:
            try:
                out, _ = proc.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                self.fail("tests/test_v4r.py did not finish within 60s "
                          "on an open-pipe stdin")
            self.assertEqual(proc.returncode, 0,
                             out.decode(errors="replace")[-2000:])
        finally:
            os.close(write_fd)

    def test_v4r_leaves_no_marked_or_child_process(self):
        # The same open pipe as the timeout test: a backgrounded run's stdin.
        # The marker is this test's alone, so what the file leaves behind is
        # visible here and is not the run that launched this process.
        marker = f"v4r-{os.getpid()}-{time.time_ns()}"
        read_fd, write_fd = os.pipe()
        proc = subprocess.Popen(
            [sys.executable, str(REPO / "tests/test_v4r.py")],
            stdin=read_fd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=str(REPO), preexec_fn=_cap_500mb, start_new_session=True,
            env={**os.environ, "AGENTKIT_RUN": marker})
        os.close(read_fd)
        try:
            try:
                out, _ = proc.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                _end_fixture(marker, proc.pid)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                self.fail("tests/test_v4r.py did not finish within 60s "
                          "on an open-pipe stdin")
            text = out.decode(errors="replace")
            self.assertEqual(proc.returncode, 0, text[-2000:])
            self.assertNotIn("Exception in thread", text)
            self.assertNotIn("AssertionError: probe", text)
            marked, children = _left_behind(marker, proc.pid)
            if marked or children:
                _end_fixture(marker, proc.pid)
            self.assertEqual(marked, [], "a process still carries the test's marker")
            self.assertEqual(children, [], "a child of the test is still alive")
        finally:
            os.close(write_fd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
