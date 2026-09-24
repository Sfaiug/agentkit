"""Every agent process lives in agentkit's own systemd slice, and a frozen host is not silent.

Offline: a fake `systemd-run`, `systemctl`, `tmux` and `nproc` on PATH that record their argv,
a fake `/proc/self/cgroup`, `/proc` and `/sys/fs/cgroup`, a fake `/proc/meminfo`, and a
throwaway HOME.  No real user manager is asked, no unit is started, no cgroup is frozen, and
the only slice name any of it names is the test server's own.
"""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from test_v4n import REPO, Sandbox
from agentkit import config, orch, run, watch

# One spy for every command the slice rests on: it records its argv and answers the way the
# case under test needs it to, so nothing here can reach the account's own manager.
SPY = '''#!{python}
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with pathlib.Path(os.environ["AK_SLICE_LOG"]).open("a") as fh:
    fh.write(json.dumps([name, *sys.argv[1:]]) + "\\n")
if name == "systemctl":
    if sys.argv[1:3] == ["--user", "is-system-running"]:
        if os.environ.get("AK_SLICE_MANAGER") != "1":
            sys.stderr.write("Failed to connect to bus: No such file or directory\\n")
            sys.exit(1)
        print("running")
    elif sys.argv[1:2] == ["show"]:
        print(os.environ.get("AK_SLICE_USER_TASKS", "8192"))
elif name == "nproc":
    print(os.environ.get("AK_SLICE_CPUS", "4"))
elif name == "tmux":
    # a server that is not up answers nothing about itself, which is how `ak orch` and
    # an update know that theirs is the command starting one
    if (os.environ.get("AK_SLICE_SERVER_UP") != "1"
            and ("source-file" in sys.argv or "list-sessions" in sys.argv)):
        sys.exit(1)
sys.exit(0)
'''

CGROUP = "/user.slice/user-1000.slice/user@1000.service/agentkit.slice/tmux-spawn-a.scope"
MEMINFO = "MemTotal:       16777216 kB\nMemFree:         2097152 kB\n"


class Slice(Sandbox):
    def setUp(self):
        super().setUp()
        self.bin = self.root / "bin"
        self.bin.mkdir(parents=True, exist_ok=True)
        self.log = self.root / "commands.jsonl"
        for name in ("systemd-run", "systemctl", "tmux", "nproc"):
            path = self.bin / name
            path.write_text(SPY.format(python=sys.executable))
            path.chmod(0o755)
        # to `ak` a user manager is something listening on the control socket in the uid's
        # runtime directory, and to `install.sh` it is what `systemctl` answers; this host
        # has both, of its own
        # a runtime directory of this test's own, short enough for a unix socket path: the
        # checkout this suite runs from is deeper than the 108 bytes AF_UNIX allows
        self.runtime = Path(tempfile.mkdtemp(prefix="ak-slice-"))
        self.addCleanup(shutil.rmtree, self.runtime, ignore_errors=True)
        (self.runtime / "systemd").mkdir(parents=True, exist_ok=True)
        self.manager = self.runtime / orch.MANAGER_SOCKET
        self.listening = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.listening.close)
        self.listening.bind(str(self.manager))
        self.listening.listen(1)
        (self.runtime / "bus").touch()
        self.stack.enter_context(patch.dict(os.environ, {
            "PATH": f"{self.bin}:{os.environ['PATH']}", "AK_SLICE_LOG": str(self.log),
            "AK_SLICE_MANAGER": "1", "XDG_RUNTIME_DIR": str(self.runtime),
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={self.runtime}/bus"}))
        # where this process runs decides whether a child of its own can be put in the slice,
        # and a test may not depend on where the suite itself was started
        self.own_cgroup = self.root / "own-cgroup"
        self.own_cgroup.write_text(f"0::/user.slice/user-{os.getuid()}.slice/"
                                   f"user@{os.getuid()}.service/app.slice/ak.scope\n")
        self.stack.enter_context(patch.object(orch, "OWN_CGROUP", self.own_cgroup))
        # and the slice says what it holds in its own directory, which is this test's too
        self.cgroup = self.root / "cgroup"
        self.stack.enter_context(patch.object(orch, "CGROUP_ROOT", self.cgroup))
        self.slice_dir = (self.cgroup / "user.slice" / f"user-{os.getuid()}.slice"
                          / f"user@{os.getuid()}.service" / "agentkit.slice"
                          / "agentkit-test.slice")
        self.slice_dir.mkdir(parents=True)
        (self.slice_dir / "pids.current").write_text("9\n")
        (self.slice_dir / "pids.max").write_text("36\n")
        # nothing in this file may signal a process group: every pid here is a fake, and a
        # fake pid is somebody else's process on a busy host
        self.killed = []
        self.stack.enter_context(patch.object(
            orch.os, "killpg", side_effect=lambda group, sig: self.killed.append(group)))
        # a detached launch is its own group leader, which is what `start_new_session` makes
        # of a real one; here it is said plainly, because no fake pid has a group to read
        self.stack.enter_context(patch.object(orch.os, "getpgid", side_effect=lambda pid: pid))
        # both answers are asked once per process and kept; a test that changes the host has
        # to say so, and every test starts from an unasked question
        orch._MANAGER.clear()
        orch._SLICE.clear()
        self.addCleanup(orch._SLICE.clear)
        self.addCleanup(orch._MANAGER.clear)

    def no_manager(self, stale=False):
        """No user systemd manager here: nothing listening, and with `stale` not even gone.

        A manager that has died leaves its socket behind on a host whose runtime directory
        outlives it, and a file is not a manager.
        """
        self.listening.close()
        if not stale:
            self.manager.unlink()
        orch._MANAGER.clear()
        orch._SLICE.clear()

    def from_cron(self):
        """This process is a tick from cron: in the system's cgroup, not the manager's."""
        self.own_cgroup.write_text("0::/system.slice/cron.service\n")

    def commands(self, name):
        """Every recorded call of that command, argv by argv."""
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()
                if json.loads(line)[0] == name]

    def started(self):
        """The argv that started the seat: the first command carrying `new-session`."""
        return next(argv for argv in self.commands("systemd-run") + self.commands("tmux")
                    if "new-session" in argv)

    def popen(self, status=0, pid=4242, ran=True, stopped=True, loaded="not-found"):
        """Patch `Popen` after the fakes have answered: `subprocess.run` is built on it.

        A placed launch that runs leaves the mark the real `sh` writes before it becomes the
        work; `ran=False` is a placement that was refused -- its client is gone -- and
        `ran=None` one still on its way, which has neither marked nor given up.  `status` is
        what `systemd-run` itself reports, `stopped` what the manager answers when a
        placement still on its way is asked to end, and `loaded` what it says about a unit
        an earlier attempt left claimed.
        """
        self.assertTrue(orch.user_manager())
        # MagicMocks, because ending a placement runs one command of its own
        self.started = started = MagicMock(
            pid=pid, **{"wait.return_value": status,
                        "poll.return_value": None if ran is not False else 1,
                        "communicate.return_value": (b"", b"")})
        halted = MagicMock(**{"poll.return_value": 0 if stopped else 1,
                              "wait.return_value": 0 if stopped else 1,
                              "communicate.return_value": (b"", b"")})
        shown = MagicMock(**{"poll.return_value": 0, "wait.return_value": 0,
                             "communicate.return_value": (f"{loaded}\n", "")})
        for mock in (started, halted, shown):
            mock.__enter__.return_value = mock       # `subprocess.run` opens it as one

        def spawned(command, **kwargs):
            if command[:3] == ["systemctl", "--user", "stop"]:
                return halted
            if command[:3] == ["systemctl", "--user", "show"]:
                return shown
            marker = next((arg for arg in command if arg.endswith(".launched")), None)
            if marker and ran:
                Path(marker).write_text(str(pid))
            return started
        return patch.object(orch.subprocess, "Popen", side_effect=spawned)


class Seats(Slice):
    def test_a_seat_starts_in_the_slice_where_a_user_manager_runs(self):
        orch.start("in-slice", self.root, ["sleep", "60"], "astra")
        argv = self.started()
        self.assertEqual(argv[:6], ["systemd-run", "--user", "--slice=agentkit-test.slice",
                                    "--scope", "--quiet", "--unit=agentkit-seat-in-slice"])
        self.assertEqual(argv[6:9], ["tmux", "-L", "agentkit-test"])
        self.assertIn("new-session", argv)

    def test_b_seat_starts_plainly_where_no_manager_answers(self):
        self.no_manager()
        orch.start("plain", self.root, ["sleep", "60"], "astra")
        self.assertEqual(self.started()[:3], ["tmux", "-L", "agentkit-test"])
        self.assertEqual(self.commands("systemd-run"), [])

    def test_c_a_server_already_up_keeps_the_slice_it_was_started_in(self):
        # only the command that starts a server can place it; a second seat joins it where
        # it is, and asking for a scope around a client would leave a unit nobody wants
        self.stack.enter_context(patch.dict(os.environ, {"AK_SLICE_SERVER_UP": "1"}))
        orch.start("joining", self.root, ["sleep", "60"], "astra")
        self.assertEqual(self.started()[:3], ["tmux", "-L", "agentkit-test"])
        self.assertEqual(self.commands("systemd-run"), [])

    def test_d_a_tick_from_cron_has_the_manager_start_the_server_itself(self):
        # the kernel refuses the manager the move out of the system's own cgroup, so a seat
        # the tick brings back after a reboot cannot be scoped -- and is placed all the same,
        # by the manager, so that the tick's servers are in the slice like everybody else's
        self.from_cron()
        self.assertFalse(orch.can_scope())
        orch.start("after-a-reboot", self.root, ["sleep", "60"], "astra")
        argv = self.started()
        self.assertEqual(argv[:5], ["systemd-run", "--user", "--slice=agentkit-test.slice",
                                    "--quiet", "--collect"])
        self.assertIn("--unit=agentkit-seat-after-a-reboot", argv)
        self.assertIn("--property=Type=forking", argv)   # what it leaves behind is the server
        tmux = argv.index("tmux")
        self.assertEqual(argv[tmux:tmux + 3], ["tmux", "-L", "agentkit-test"])
        self.assertIn("new-session", argv)

    def test_f_the_ticks_resume_runs_in_the_slice_with_the_user_bus(self):
        run_id = "20260101-0900-resume"
        (config.RUNS / run_id).mkdir(parents=True)
        run.save_state(config.RUNS / run_id, {"run_id": run_id, "state": "running"})
        # a tick from cron inherits no session at all, so the bus is derived from the uid --
        # and a service is what the manager starts inside the slice itself, which is the only
        # way in from a cgroup a scope may not be moved out of
        self.from_cron()
        with self.popen() as popen, patch.dict(os.environ):
            os.environ.pop("XDG_RUNTIME_DIR")          # cron hands over neither of these
            os.environ.pop("DBUS_SESSION_BUS_ADDRESS")
            self.assertTrue(watch.launch_resume(run_id))
        argv, env = popen.call_args.args[0], popen.call_args.kwargs["env"]
        self.assertEqual(argv[:5], ["systemd-run", "--user", "--slice=agentkit-test-runs.slice",
                                    "--quiet", "--collect"])
        self.assertIn(f"--unit=agentkit-run-{run_id}", argv)
        self.assertIn(f"--property=StandardOutput=append:{config.RUNS / run_id / 'log.txt'}",
                      argv)
        self.assertIn("--setenv=AK_RUN_DEPTH=0", argv)
        self.assertEqual(argv[-3:], ["run", "resume", run_id])
        self.assertEqual(env["XDG_RUNTIME_DIR"], f"/run/user/{os.getuid()}")
        self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"],
                         f"unix:path=/run/user/{os.getuid()}/bus")

    def test_g_a_resume_the_slice_will_not_take_is_started_plainly(self):
        run_id = "20260101-0900-refused"
        self.from_cron()                 # a service, and the manager will not take its unit
        (config.RUNS / run_id).mkdir(parents=True)
        run.save_state(config.RUNS / run_id, {"run_id": run_id, "state": "running"})
        said = []
        with self.popen(status=1) as popen:      # the manager would not take the unit
            self.assertTrue(watch.launch_resume(run_id, log=said.append))
        self.assertEqual(popen.call_count, 2)
        second = popen.call_args_list[1].args[0]
        self.assertEqual(second[-3:], ["run", "resume", run_id])
        self.assertNotIn("systemd-run", second[0])
        self.assertTrue(any("started plainly" in line for line in said), said)

    def test_h_orch_list_says_where_the_agents_run_and_where_they_do_not(self):
        line = "slice agentkit-test.slice · 9 tasks · 25% of its ceiling"
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.cmd_list([]), 0)
        self.assertIn(line, out.getvalue())
        # `ak doctor` is the other screen that says it, above the tick's own state; its effort
        # line asks each harness for its models, which no test does of the real ones
        self.stack.enter_context(patch.object(config, "catalog", return_value=[]))
        with redirect_stdout(io.StringIO()) as doctor:
            self.assertEqual(watch.doctor([]), 0)
        self.assertEqual(doctor.getvalue().splitlines()[0], line)
        self.assertIn("tick  lock free", doctor.getvalue())
        self.no_manager()
        with redirect_stdout(io.StringIO()) as plain, redirect_stderr(io.StringIO()):
            self.assertEqual(orch.cmd_list([]), 0)
        self.assertIn("no slice (no user systemd manager)", plain.getvalue())
        with redirect_stdout(io.StringIO()) as doctor:
            self.assertEqual(watch.doctor([]), 0)
        self.assertIn("no slice (no user systemd manager)", doctor.getvalue())
        # and `ak orch why` is where the fallback is spelled out, for one seat
        seat = {"name": "seat", "path": str(self.root), "created": int(time.time()),
                "attached": False, "exited": False, "legacy": False, "resumable": False}
        config.save_session(self.cfg, "seat", "astra", ["opus"], {"cwd": str(self.root)})
        with patch.object(orch, "listing", return_value=[seat]), \
                redirect_stdout(io.StringIO()) as why, redirect_stderr(io.StringIO()):
            self.assertEqual(orch.cmd_why(["seat"]), 0)
        self.assertIn("no slice (no user systemd manager); this seat's tmux server was "
                      "started plainly", why.getvalue())

    def test_i_a_ceiling_is_read_before_the_first_agent_starts(self):
        # nothing has run in the slice yet, so it has no directory and no `pids.max`; the
        # ceiling `install.sh` wrote is real all the same, and the line says so
        for name in ("pids.current", "pids.max"):
            (self.slice_dir / name).unlink()
        self.slice_dir.rmdir()
        drop_in = (self.root / ".config/systemd/user/agentkit-test.slice.d")
        drop_in.mkdir(parents=True)
        (drop_in / "limits.conf").write_text("[Slice]\nTasksMax=4096\nCPUQuota=700%\n")
        self.assertEqual(orch.slice_tasks(), (0, 4096))
        self.assertEqual(orch.slice_line(),
                         "slice agentkit-test.slice · 0 tasks · 0% of its ceiling")
        # and what `systemctl --user set-property` persists beside it wins, as it does there
        control = self.root / ".config/systemd/user.control/agentkit-test.slice.d"
        control.mkdir(parents=True)
        (control / "50-TasksMax.conf").write_text("[Slice]\nTasksMax=512\n")
        orch._SLICE.clear()
        self.assertEqual(orch.slice_line(),
                         "slice agentkit-test.slice · 0 tasks · 0% of its ceiling")
        self.assertEqual(orch.slice_tasks(), (0, 512))

    def test_j_only_a_manager_that_answers_counts_as_a_manager(self):
        # a bus socket may be anybody's -- a session bus without systemd behind it is one --
        # and an address that names no path is still a bus this machine has
        with patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": "unix:abstract=/tmp/dbus-x"}):
            self.assertTrue(orch.user_manager())
        # the socket a manager that has gone left behind answers nothing, and a launch that
        # believed it would fail again on every run instead of starting plainly once
        self.no_manager(stale=True)
        self.assertTrue(self.manager.exists())
        self.assertFalse(orch.user_manager())
        self.assertEqual(orch.slice_line(), orch.NO_SLICE)


class Detached(Slice):
    """What the toolkit starts without a seat -- a `--bg` run, a job, an update -- goes in too."""

    def test_i_a_background_run_and_a_job_are_started_in_the_slice(self):
        run_dir = config.RUNS / "20260101-0900-detached"
        run_dir.mkdir(parents=True)
        run.save_state(run_dir, {"run_id": run_dir.name, "state": "queued"})
        with self.popen() as popen, redirect_stdout(io.StringIO()):
            run.spawn_bg(run_dir, ["resume", run_dir.name])
        argv = popen.call_args.args[0]
        self.assertEqual(argv[:6], ["systemd-run", "--user", "--slice=agentkit-test-runs.slice",
                                    "--scope", "--quiet",
                                    f"--unit=agentkit-run-{run_dir.name}"])
        self.assertEqual(argv[-3:], ["run", "resume", run_dir.name])
        # the receipt still names a process that is alive for as long as the run is: the scope
        # holds the loop, so reaping sees a launcher rather than a gap
        self.assertEqual(run.read_state(run_dir)["pid"], 4242)
        job_dir = config.RUNS / "20260101-0900-job"
        job_dir.mkdir(parents=True)
        with self.popen(pid=4343) as popen, patch.object(run, "read_job", return_value={}), \
                patch.object(run, "save_job"), redirect_stdout(io.StringIO()):
            run.spawn_job_bg(job_dir)
        self.assertEqual(popen.call_args.args[0][:6],
                         ["systemd-run", "--user", "--slice=agentkit-test-runs.slice", "--scope",
                          "--quiet", f"--unit=agentkit-job-{job_dir.name}"])

    def test_j_an_update_that_starts_the_jobs_server_starts_it_in_the_slice(self):
        with patch.object(orch, "job_running", return_value=False):
            orch.start_update()
        argv = next(a for a in self.commands("systemd-run") if "new-session" in a)
        self.assertEqual(argv[:6], ["systemd-run", "--user",
                                    "--slice=agentkit-test-jobs.slice", "--scope", "--quiet",
                                    f"--unit=agentkit-job-{orch.UPDATE_JOB}"])
        self.assertEqual(argv[6:9], ["tmux", "-L", "agentkit-test-jobs"])

    def test_k_a_run_a_tick_detaches_goes_in_as_a_service(self):
        # a scope would have to move this process out of the system's cgroup, which nothing
        # unprivileged may do; the manager starting the work itself is the way in from there
        self.from_cron()
        run_dir = config.RUNS / "20260101-0900-from-cron"
        run_dir.mkdir(parents=True)
        run.save_state(run_dir, {"run_id": run_dir.name, "state": "queued"})
        with self.popen(pid=5151) as popen, redirect_stdout(io.StringIO()):
            run.spawn_bg(run_dir, ["resume", run_dir.name])
        argv = popen.call_args.args[0]
        self.assertEqual(argv[:5], ["systemd-run", "--user", "--slice=agentkit-test-runs.slice",
                                    "--quiet", "--collect"])
        self.assertIn(f"--unit=agentkit-run-{run_dir.name}", argv)
        # the client is gone the moment the unit is taken; the receipt names what the manager
        # forked, so nothing reaps a run for a launcher that was never the work
        self.assertEqual(run.read_state(run_dir)["pid"], 5151)

    def test_l_a_run_nothing_can_place_at_all_is_started_plainly(self):
        self.from_cron()
        self.no_manager()
        run_dir = config.RUNS / "20260101-0900-plainly"
        run_dir.mkdir(parents=True)
        run.save_state(run_dir, {"run_id": run_dir.name, "state": "queued"})
        self.assertFalse(orch.user_manager())    # asked before Popen is taken away
        with patch.object(orch.subprocess, "Popen", return_value=Mock(pid=4242)) as popen, \
                redirect_stdout(io.StringIO()):
            run.spawn_bg(run_dir, ["resume", run_dir.name])
        self.assertEqual(popen.call_args.args[0][-3:], ["run", "resume", run_dir.name])
        self.assertNotIn("systemd-run", popen.call_args.args[0][0])
        self.assertEqual(run.read_state(run_dir)["pid"], 4242)

    def test_m_work_that_finishes_at_once_is_never_started_twice(self):
        # the mark is written before the work begins, so a task that ends in a moment is
        # still a task that ran: neither its exit status nor its speed starts it again
        run_dir = config.RUNS / "20260101-0900-brief"
        run_dir.mkdir(parents=True)
        run.save_state(run_dir, {"run_id": run_dir.name, "state": "queued"})
        with self.popen(status=7) as popen, redirect_stdout(io.StringIO()):
            run.spawn_bg(run_dir, ["resume", run_dir.name])   # the work ran, and failed fast
        self.assertEqual(popen.call_count, 1)
        self.assertIn("--scope", popen.call_args.args[0])
        self.assertEqual(run.read_state(run_dir)["pid"], 4242)   # the pid it marked as its own
        # and the same where only a service can reach: the manager took the unit and the
        # work was over before anything looked, which is not work that never began
        self.from_cron()
        job_dir = config.RUNS / "20260101-0900-brief-job"
        job_dir.mkdir(parents=True)
        saved = []
        with self.popen(pid=4343) as popen, patch.object(run, "read_job", return_value={}), \
                patch.object(run, "save_job", side_effect=lambda _d, job: saved.append(job)), \
                redirect_stdout(io.StringIO()):
            run.spawn_job_bg(job_dir)
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(saved[0]["pid"], 4343)

    def test_n_a_placement_that_never_ran_the_work_starts_it_plainly(self):
        # a scope the manager would not make, and a unit it took without ever forking: in
        # both the work left no mark, and in both it has to start anyway
        self.stack.enter_context(patch.object(orch, "SLICE_WAIT", 0.2))
        session = self.own_cgroup.read_text()
        for kind, where in (("service", self.from_cron),
                            ("scope", lambda: self.own_cgroup.write_text(session))):
            where()
            run_dir = config.RUNS / f"20260101-0900-lost-{kind}"
            run_dir.mkdir(parents=True)
            run.save_state(run_dir, {"run_id": run_dir.name, "state": "queued"})
            with self.popen(ran=False) as popen, redirect_stdout(io.StringIO()):
                run.spawn_bg(run_dir, ["resume", run_dir.name])
            argvs = [call.args[0] for call in popen.call_args_list]
            self.assertEqual(argvs[0][0], "systemd-run")
            # a unit the manager took and never forked may still be on its way, so it is
            # stopped before the second start; a client that is gone was refused, and there
            # is nothing left to stop
            stops = [argv for argv in argvs if argv[:3] == ["systemctl", "--user", "stop"]]
            self.assertEqual(stops, [["systemctl", "--user", "stop",
                                      f"agentkit-run-{run_dir.name}.service"]]
                             if kind == "service" else [])
            self.assertEqual(len(argvs), 3 if kind == "service" else 2)
            plain = argvs[-1]
            self.assertNotIn("systemd-run", plain[0])
            self.assertEqual(plain[-3:], ["run", "resume", run_dir.name])
            saved = run.read_state(run_dir)
            self.assertEqual(saved["pid"], 4242)      # the plain launch, named and reapable
            self.assertFalse(saved["launch_pending"])
            self.assertIn("did not go into", (run_dir / "log.txt").read_text())

    def test_o_a_placement_still_on_its_way_is_stopped_before_the_second_start(self):
        # neither a mark nor a client that gave up: something may still be coming, and the
        # plain start below would be the second of it
        self.stack.enter_context(patch.object(orch, "SLICE_WAIT", 0.2))
        run_dir = config.RUNS / "20260101-0900-on-its-way"
        run_dir.mkdir(parents=True)
        run.save_state(run_dir, {"run_id": run_dir.name, "state": "queued"})
        with self.popen(ran=None) as popen, redirect_stdout(io.StringIO()):
            run.spawn_bg(run_dir, ["resume", run_dir.name])
        argvs = [call.args[0] for call in popen.call_args_list]
        self.assertIn("--scope", argvs[0])
        # a scope is this process's own to end, group and all, and once it is ended the work
        # can only be the plain start below
        self.assertEqual(self.killed, [4242])
        self.assertEqual(len(argvs), 2)
        self.assertNotIn("systemd-run", argvs[1][0])
        self.assertEqual(argvs[1][-3:], ["run", "resume", run_dir.name])

    def test_p_a_placement_that_cannot_be_ended_is_not_started_again(self):
        # the manager took the unit, nothing marked, and it will not say the unit stopped:
        # it may yet bring the work up, so nothing is started here at all and the caller is
        # told -- a run that did not start beats two runs of the same task
        self.stack.enter_context(patch.object(orch, "SLICE_WAIT", 0.2))
        self.from_cron()
        run_dir = config.RUNS / "20260101-0900-in-doubt"
        run_dir.mkdir(parents=True)
        run.save_state(run_dir, {"run_id": run_dir.name, "state": "queued"})
        with self.popen(ran=None, stopped=False) as popen, redirect_stdout(io.StringIO()):
            with self.assertRaises(config.Error) as refused:
                run.spawn_bg(run_dir, ["resume", run_dir.name])
        self.assertIn("neither running", str(refused.exception))
        argvs = [call.args[0] for call in popen.call_args_list]
        self.assertEqual([argvs[0][0], argvs[1][:3]],
                         ["systemd-run", ["systemctl", "--user", "stop"]])
        self.assertEqual(len(argvs), 2)          # and no second start of the work
        self.assertEqual(run.read_state(run_dir)["state"], "interrupted")
        self.assertEqual((config.TMP / f"agentkit-run-{run_dir.name}.placed").read_text(),
                         f"agentkit-run-{run_dir.name}.service")

    def test_q_a_claim_an_earlier_attempt_left_blocks_the_next_start(self):
        # that unit may still be the manager's to bring up, so until it says the unit is
        # gone nothing starts a second copy of the same work -- and once it is gone, the
        # claim is the stale file it always was and the work starts as usual
        self.from_cron()
        run_dir = config.RUNS / "20260101-0900-claimed"
        run_dir.mkdir(parents=True)
        run.save_state(run_dir, {"run_id": run_dir.name, "state": "queued"})
        unit = f"agentkit-run-{run_dir.name}"
        (config.TMP / f"{unit}.placed").write_text(f"{unit}.service")
        with self.popen(loaded="loaded") as popen, redirect_stdout(io.StringIO()):
            with self.assertRaises(config.Error) as refused:
                run.spawn_bg(run_dir, ["resume", run_dir.name])
        self.assertIn("still in", str(refused.exception))
        self.assertEqual([call.args[0][:3] for call in popen.call_args_list],
                         [["systemctl", "--user", "show"]])     # nothing was started at all
        with self.popen() as popen, redirect_stdout(io.StringIO()):
            run.spawn_bg(run_dir, ["resume", run_dir.name])
        self.assertEqual([call.args[0][:3] for call in popen.call_args_list][0],
                         ["systemctl", "--user", "show"])
        self.assertEqual(popen.call_args_list[1].args[0][0], "systemd-run")
        self.assertFalse((config.TMP / f"{unit}.placed").exists())

    def test_r_a_claim_outlives_a_bus_that_cannot_be_asked(self):
        # the manager is unreachable now, and its answer is the only thing that could say
        # the unit an earlier attempt left is gone: a plain start here would be the second
        # of that work, and outside the slice at that
        run_dir = config.RUNS / "20260101-0900-no-bus"
        run_dir.mkdir(parents=True)
        run.save_state(run_dir, {"run_id": run_dir.name, "state": "queued"})
        unit = f"agentkit-run-{run_dir.name}"
        claim = config.TMP / f"{unit}.placed"
        claim.write_text(f"{unit}.service")
        self.no_manager()
        self.assertFalse(orch.user_manager())
        with patch.object(orch.subprocess, "Popen",
                          side_effect=OSError("no systemctl here")) as popen, \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(config.Error) as refused:
                run.spawn_bg(run_dir, ["resume", run_dir.name])
        self.assertIn("still in", str(refused.exception))
        self.assertEqual([call.args[0][:3] for call in popen.call_args_list],
                         [["systemctl", "--user", "show"]])   # nothing was started at all
        self.assertTrue(claim.exists())          # and the question stands for the next try

    def test_s_a_units_command_line_reaches_the_work_as_it_was_written(self):
        # systemd reads a dollar in a unit's command as the start of a variable; the work
        # has to be handed what a scope would have handed it, mark and arguments alike
        self.from_cron()
        out = self.root / "placed.log"
        with self.popen() as popen:
            self.assertEqual(orch.start_in_slice(["work", "a$b"], "agentkit-dollars",
                                                 {"PATH": os.environ["PATH"]}, out), 4242)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[-2:], ["work", "a$$b"])
        self.assertIn('printf %s "$$$$" >"$$0"; exec "$$@"', argv)
        # and the mark is the unit's own, taken away once it has been read
        self.assertEqual(sorted(config.TMP.glob("*.launched")), [])

    def test_t_a_launch_the_manager_cannot_take_at_all_still_happens(self):
        # `systemd-run` gone from PATH between the answer and the launch is still a run that
        # has to start: the plain start is tried before anything is given up on
        run_id = "20260101-0900-gone"
        (config.RUNS / run_id).mkdir(parents=True)
        run.save_state(config.RUNS / run_id, {"run_id": run_id, "state": "running"})
        said = []
        self.assertTrue(orch.user_manager())
        with patch.object(orch.subprocess, "Popen",
                          side_effect=[OSError("no systemd-run"), Mock(pid=77)]) as popen:
            self.assertTrue(watch.launch_resume(run_id, log=said.append))
        self.assertEqual(popen.call_count, 2)
        self.assertEqual(popen.call_args.args[0][-3:], ["run", "resume", run_id])
        self.assertTrue(any("started plainly" in line for line in said), said)


class Installer(Slice):
    """The ceiling `install.sh` writes, in a HOME of this test's own and nowhere else."""

    SECTION = "# --- (g3) the ceiling for everything the toolkit starts"
    NEXT = "# --- (h) a new phone key"

    def setUp(self):
        super().setUp()
        self.meminfo = self.root / "meminfo"
        self.meminfo.write_text(MEMINFO)                 # 16 GiB, as /proc/meminfo says it

    def install(self, home, **env):
        source = (REPO / "install.sh").read_text()
        body = source[source.index(self.SECTION):source.index(self.NEXT)]
        prelude = ('set -euo pipefail\n'
                   f'HOME={shlex.quote(str(home))}\nROLE=server\nSANDBOX=0\n'
                   'have() { command -v "$1" >/dev/null 2>&1; }\n'
                   'note() { echo "note: $*" >&2; }\n')
        return subprocess.run(["bash", "-c", prelude + body], capture_output=True, text=True,
                              env={**os.environ, "MEMINFO": str(self.meminfo), **env},
                              timeout=60)

    def test_l_the_ceiling_is_written_once_from_this_hosts_own_numbers(self):
        home = self.root / "fresh-home"
        home.mkdir()
        limits = home / ".config/systemd/user/agentkit.slice.d/limits.conf"
        result = self.install(home, AK_SLICE_USER_TASKS="8192", AK_SLICE_CPUS="4")
        self.assertEqual(result.returncode, 0, result.stderr)
        written = limits.read_text()
        self.assertIn("[Slice]\nTasksMax=6144\n", written)       # three quarters of 8192
        # 60% and 70% of MemTotal, in mebibytes: 16 GiB of memory, and nothing rounded up
        self.assertIn("MemoryHigh=9830M\nMemoryMax=11468M\n", written)
        self.assertIn("CPUQuota=300%\n", written)                # four cores, one left over
        seats = (home / ".config/systemd/user/agentkit-seats.slice.d/weights.conf").read_text()
        runs = (home / ".config/systemd/user/agentkit-runs.slice.d/weights.conf").read_text()
        self.assertIn("CPUWeight=100\nIOWeight=100\n", seats)
        self.assertIn("CPUWeight=40\nIOWeight=40\n", runs)
        self.assertIn(["systemctl", "--user", "daemon-reload"], self.commands("systemctl"))
        # a second install is not a second answer: the file is the owner's from now on
        limits.write_text("[Slice]\nTasksMax=12\n")
        again = self.install(home, AK_SLICE_USER_TASKS="8192", AK_SLICE_CPUS="4")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(limits.read_text(), "[Slice]\nTasksMax=12\n")
        self.assertIn("left as it is", again.stdout)

    def test_n_an_install_without_a_session_still_finds_the_manager(self):
        # a reinstall from cron or over ssh without a login shell inherits no session: the
        # runtime directory is the uid's own and the bus is the socket inside it, and a
        # ceiling must not be skipped for want of two variables
        home = self.root / "sessionless-home"
        home.mkdir()
        result = self.install(home, XDG_RUNTIME_DIR="", DBUS_SESSION_BUS_ADDRESS="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TasksMax=6144",
                      (home / ".config/systemd/user/agentkit.slice.d/limits.conf").read_text())
        asked = [argv for argv in self.commands("systemctl")
                 if argv[1:3] == ["--user", "is-system-running"]]
        self.assertTrue(asked, self.commands("systemctl"))

    def test_m_a_host_that_says_less_about_itself_still_gets_a_ceiling(self):
        home = self.root / "infinite-home"
        home.mkdir()
        limits = home / ".config/systemd/user/agentkit.slice.d/limits.conf"
        self.meminfo.write_text("MemFree: 12 kB\n")      # no MemTotal to take a share of
        result = self.install(home, AK_SLICE_USER_TASKS="infinity", AK_SLICE_CPUS="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        written = limits.read_text()
        self.assertIn("TasksMax=3072\n", written)        # nothing to take a share of
        self.assertIn("CPUQuota=100%\n", written)        # never less than one core
        self.assertIn("MemoryHigh=60%\nMemoryMax=70%\n", written)   # systemd reads the share
        mac = self.root / "mac-home"
        mac.mkdir()
        result = self.install(mac, AK_SLICE_MANAGER="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((mac / ".config").exists())
        self.assertIn("no user systemd manager here; seats start plainly", result.stdout)


class Frozen(Slice):
    """A run the host froze is silent by definition, and the stall rules leave it alone."""

    def setUp(self):
        super().setUp()
        self.proc = self.root / "proc"
        self.stack.enter_context(patch.object(watch, "PROC", self.proc))
        self.killed, self.resumed = [], []
        self.stack.enter_context(patch.object(
            watch, "kill_tree", side_effect=lambda pid, log=None: self.killed.append(pid)))
        self.stack.enter_context(patch.object(
            watch, "launch_resume", side_effect=lambda run_id, log=None: (
                self.resumed.append(run_id), True)[1]))
        # this process stands in for the run's loop, so the receipt names a process that is
        # really alive and really identifiable: a freeze is only ever read off the run's own
        self.pid = os.getpid()
        (self.proc / str(self.pid)).mkdir(parents=True)
        (self.proc / str(self.pid) / "cgroup").write_text(f"0::{CGROUP}\n")
        for depth in range(1, len(CGROUP.strip("/").split("/")) + 1):
            held = self.cgroup.joinpath(*CGROUP.strip("/").split("/")[:depth])
            held.mkdir(parents=True, exist_ok=True)
            (held / "cgroup.freeze").write_text("0\n")
        self.held = self.cgroup / CGROUP.strip("/").rsplit("/", 1)[0] / "cgroup.freeze"
        self.run_dir = config.RUNS / "20260101-0900-held"
        self.run_dir.mkdir(parents=True)
        run.save_state(self.run_dir, {"run_id": self.run_dir.name, "state": "running",
                                      "silence_minutes": 30, **run.process_owner()})
        # the run's own newest write, not the clock: a fixture's mtime is when this test made
        # it, and the sandbox around it holds `time.time` still
        self.started = watch.run_last_write(self.run_dir)

    def tick(self, when, dry_run=False):
        lines = []
        watch.recover_runs(cfg=self.cfg, dry_run=dry_run, log=lines.append, now=when)
        return lines

    def log_lines(self):
        path = self.run_dir / "log.txt"
        return path.read_text().splitlines() if path.exists() else []

    def frozen_lines(self):
        return [line for line in self.log_lines() if "stall clock paused" in line]

    def test_n_a_frozen_run_is_not_stopped_and_is_said_once(self):
        self.held.write_text("1\n")           # the slice above the run's own cgroup is held
        frozen = self.started + 10 * 3600
        self.assertEqual(self.tick(frozen), [])
        self.assertEqual(self.tick(frozen + 300), [])
        self.assertEqual(len(self.frozen_lines()), 1, self.log_lines())
        self.assertIn("host frozen since", self.frozen_lines()[0])
        state = run.read_state(self.run_dir)
        self.assertEqual(state["state"], "running")
        self.assertEqual(state.get("stalls", []), [])
        self.assertEqual(state["frozen_since"], frozen)
        self.assertEqual((self.resumed, self.killed), ([], []))
        # a dry run says what it would do to the clock and touches nothing
        self.held.write_text("0\n")
        self.assertEqual(self.tick(frozen + 600, dry_run=True),
                         [f"would restart the stall clock of {self.run_dir.name} at the thaw"])
        self.assertEqual(run.read_state(self.run_dir)["frozen_since"], frozen)

    def test_o_a_freeze_between_two_ticks_is_not_counted_against_the_run(self):
        # the clock is stopped as soon as the host takes the run, not once it looks stalled:
        # a freeze that begins and ends inside the silence limit still costs the run nothing
        self.held.write_text("1\n")
        frozen = self.started + 60
        self.assertEqual(self.tick(frozen), [])
        self.assertEqual(run.read_state(self.run_dir)["frozen_since"], frozen)
        self.held.write_text("0\n")
        thaw = frozen + 6 * 3600
        self.assertEqual(self.tick(thaw), [])
        self.assertEqual(run.read_state(self.run_dir)["thawed_at"], thaw)
        self.assertEqual(self.tick(thaw + 25 * 60), [])
        self.assertEqual((self.resumed, self.killed), ([], []))

    def test_p_the_stall_clock_runs_again_from_the_thaw(self):
        self.held.write_text("1\n")
        frozen = self.started + 10 * 3600
        self.tick(frozen)
        self.held.write_text("0\n")
        thaw = frozen + 4 * 3600
        self.assertEqual(self.tick(thaw), [])
        state = run.read_state(self.run_dir)
        self.assertEqual(state["thawed_at"], thaw)
        self.assertNotIn("frozen_since", state)
        # silence under the freeze was the host's: the run has the whole window again
        self.assertEqual(self.tick(thaw + 20 * 60), [])
        self.assertEqual(self.resumed, [])
        # and once it is silent for that long after the thaw, the rules act as they always did
        self.tick(thaw + 3 * 3600)
        self.assertEqual(self.resumed, [self.run_dir.name])
        self.assertEqual(len(self.frozen_lines()), 1, self.log_lines())

    def test_q_a_pid_that_is_no_longer_the_runs_freezes_nothing(self):
        # the kernel hands a pid on; a frozen stranger wearing this run's number would
        # otherwise hold its clock for good
        self.held.write_text("1\n")
        state = run.read_state(self.run_dir)
        state["process_identity"] = {**state["process_identity"], "ticks": 1}
        run.save_state(self.run_dir, state)
        self.tick(self.started + 10 * 3600)
        self.assertEqual(self.frozen_lines(), [])
        self.assertNotIn("frozen_since", run.read_state(self.run_dir))
        self.assertEqual(self.resumed, [self.run_dir.name])

    def test_r_a_run_nothing_holds_is_read_exactly_as_before(self):
        self.assertIsNone(watch.frozen_cgroup(self.pid))
        self.assertIsNone(watch.frozen_cgroup(None))
        self.tick(self.started + 10 * 3600)
        self.assertEqual(self.resumed, [self.run_dir.name])
        self.assertEqual(self.frozen_lines(), [])
        self.held.write_text("1\n")
        self.assertEqual(watch.frozen_cgroup(self.pid), str(self.held.parent))


if __name__ == "__main__":
    unittest.main(verbosity=2)
