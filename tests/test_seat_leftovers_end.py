"""A seat's scope is stopped once its harness has ended, with everything it left running.

Each launch of a seat's harness gets a scope of its own; the tick stops every launch scope
that holds no live pane's process, and never the server's own unit, a scope its harness has not
joined yet, a legacy seat's on the default server, or anything at all when tmux, a live pane's
parent or its cgroup cannot be read.  The pane's own process is its harness, whatever shell
tmux hands its line to.  Offline: a cgroup tree under a temporary directory, fake tmux
listings and fake process cgroups; no real unit or pane is touched, and one test runs a seat's
line through `sh`.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, host, orch, watch  # noqa: E402

UID = os.getuid()
MANAGER = f"user.slice/user-{UID}.slice/user@{UID}.service"
SEATS = f"{MANAGER}/agentkit.slice/agentkit-seats.slice"
SERVER = "agentkit-seat-acme.scope"           # the unit a seat's start put the server in
LIVE = "agentkit-seat-acme-1a2b3c4d.scope"    # acme's current launch
OLD = "agentkit-seat-acme-5e6f7a8b.scope"     # acme's launch before it
EXITED = "agentkit-seat-fix-api-9c0d1e2f.scope"


class SeatLeftovers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-seat-leftovers-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        own = self.root / "own-cgroup"
        own.write_text(f"0::/{MANAGER}/app.slice/shell.scope\n")
        env = patch.dict(os.environ, {"AK_CGROUP_ROOT": str(self.root / "cgroup"),
                                      "AK_CGROUP_FILE": str(own)})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(orch.SOCKET_ENV, None)
        for unit in (SERVER, LIVE, OLD, EXITED, "agentkit-job-update.scope"):
            self.scope(unit)
        # pid -> the unit it lives in
        self.cgroups = {100: SERVER, 101: LIVE, 102: EXITED}
        self.panes = "100 0 101\n100 1 102"
        self.default = (1, "no server running on /tmp/tmux-1000/default")   # the owner's
        self.stopped = []
        real = host.process_cgroup

        def cgroup(pid="self", cgroup_file=None):
            if pid == "self":
                return real(pid, cgroup_file)
            return f"/{SEATS}/{self.cgroups[pid]}" if pid in self.cgroups else None

        # pid -> its parent: a live pane is the server's child
        self.parents = {101: 100}
        for target, name, fake in (
                (orch, "user_manager", lambda: True),
                (host, "proc_stat", lambda pid, proc_root=None:
                    host.ProcStat("S", self.parents[pid], 1) if pid in self.parents else None),
                (orch, "tmux_out", self.tmux),
                (orch, "stop_scope", lambda scope, log, wait=True:
                    self.stopped.append(scope) or True),
                (host, "process_cgroup", cgroup)):
            patcher = patch.object(target, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def scope(self, unit, populated=True):
        path = self.root / "cgroup" / SEATS / unit
        path.mkdir(parents=True, exist_ok=True)
        (path / "cgroup.events").write_text(f"populated {int(populated)}\nfrozen 0\n")

    def tmux(self, *args, socket=None, timeout=None, **_kw):
        self.assertEqual(args, ("list-panes", "-a", "-F", "#{pid} #{pane_dead} #{pane_pid}"))
        self.assertIsNotNone(timeout, "a tick's tmux call waits a bounded time")
        if socket == "":
            return self.default
        self.assertEqual(socket, orch.SOCKET)
        return getattr(self, "answer", (0, self.panes))

    def sweep(self):
        lines = []
        orch.end_seat_leftovers(lines.append)
        return lines

    def test_a_launch_whose_harness_ended_is_stopped_and_the_live_one_stays(self):
        lines = self.sweep()
        self.assertEqual(sorted(self.stopped), sorted([OLD, EXITED]))
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("harness had ended" in line for line in lines), lines)

    def test_the_servers_unit_stays_though_a_seats_name_makes_it_look_like_a_launch(self):
        server = "agentkit-seat-fix-deadbeef.scope"
        self.scope(server)
        self.cgroups[100] = server
        self.sweep()
        self.assertNotIn(server, self.stopped)
        self.assertEqual(sorted(self.stopped), sorted([OLD, EXITED]))

    def test_a_launch_made_while_the_panes_were_listed_is_not_stopped(self):
        made = "agentkit-seat-new-0f0f0f0f.scope"

        def listing(*args, **kw):
            self.scope(made)     # its pane came up after tmux answered
            return 0, self.panes

        with patch.object(orch, "tmux_out", listing):
            self.sweep()
        self.assertNotIn(made, self.stopped)
        self.assertEqual(sorted(self.stopped), sorted([OLD, EXITED]))

    def test_a_scope_its_harness_has_not_joined_yet_is_not_stopped(self):
        # the manager makes a launch's scope before it moves the harness in
        self.scope("agentkit-seat-new-0f0f0f0f.scope", populated=False)
        self.sweep()
        self.assertEqual(sorted(self.stopped), sorted([OLD, EXITED]))

    def test_a_legacy_seat_on_the_default_server_keeps_its_scope(self):
        self.default = (0, "200 0 201")
        self.cgroups.update({200: "tmux-spawn-1.scope", 201: OLD})
        self.parents[201] = 200
        self.sweep()
        self.assertEqual(self.stopped, [EXITED])
        for answer in ((1, "lost server"), (0, "200 0 201\nnot a pane line")):
            with self.subTest(answer=answer):
                self.stopped.clear()
                self.default = answer
                self.sweep()
                self.assertEqual(self.stopped, [])

    def test_the_panes_own_process_is_its_harness_whatever_shell_runs_its_line(self):
        # tmux hands a pane's one command line to its default shell, and dash forks it
        with patch.object(orch, "user_manager", return_value=False), \
                patch.object(config, "STATE", self.root):
            line = orch.seat_command("acme", [sys.executable, "-c",
                                              "import os; print(os.getpid())"])
        shell = subprocess.Popen(["sh", "-c", line], stdout=subprocess.PIPE, text=True)
        out, _ = shell.communicate(timeout=60)
        self.assertEqual(int(out), shell.pid)

    def test_nothing_is_stopped_while_a_harness_cannot_be_proven_gone(self):
        for answer in ((1, "no server running on /tmp/tmux-1000/agentkit"),
                       (0, ""), (0, "100 0 101\nnot a pane line")):
            with self.subTest(answer=answer):
                self.answer = answer
                self.sweep()
                self.assertEqual(self.stopped, [])
        del self.answer
        self.parents[101] = 1          # a live pane that is not the server's own child
        self.sweep()
        self.assertEqual(self.stopped, [])
        self.parents[101] = 100
        del self.cgroups[101]          # a live pane whose cgroup cannot be read
        self.sweep()
        self.assertEqual(self.stopped, [])

    def test_nothing_is_stopped_where_no_user_manager_answers(self):
        with patch.object(orch, "user_manager", return_value=False):
            self.sweep()
        self.assertEqual(self.stopped, [])

    def test_the_tick_runs_the_pass(self):
        passes = {what: step for what, step, _dry in watch.local_passes({}, False, [].append)}
        what = "the ended seats' leftovers were not stopped"
        self.assertIn(what, passes)
        passes[what]()
        self.assertEqual(sorted(self.stopped), sorted([OLD, EXITED]))


if __name__ == "__main__":
    unittest.main()
