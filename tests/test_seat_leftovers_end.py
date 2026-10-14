"""A seat's scope is stopped once its harness has ended, with everything it left running.

Each launch of a seat's harness gets a scope of its own; the tick stops every launch scope
whose processes are each the child of one in it or of a manager, and never the server's own
unit, a scope its harness has not joined yet or is joining, a legacy seat's on the default
server, one whose harness is behind the shell its pane runs, one with a process or parent it
cannot read, or anything at all when tmux, a live pane's parent or the server's cgroup cannot
be read.  Offline: a cgroup tree under a temporary directory, a fake tmux listing and a fake
process table; no real unit, pane or process is touched.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import host, orch, watch  # noqa: E402

UID = os.getuid()
MANAGER = f"user.slice/user-{UID}.slice/user@{UID}.service"
SEATS = f"{MANAGER}/agentkit.slice/agentkit-seats.slice"
INIT = "init.scope"                           # where a manager, which adopts orphans, lives
SERVER = "agentkit-seat-acme.scope"           # the unit a seat's start put the server in
LIVE = "agentkit-seat-acme-1a2b3c4d.scope"    # acme's current launch
OLD = "agentkit-seat-acme-5e6f7a8b.scope"     # acme's launch before it
EXITED = "agentkit-seat-fix-api-9c0d1e2f.scope"
NEW = "agentkit-seat-new-0f0f0f0f.scope"


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
        # pid -> (its parent, the unit it lives in)
        self.procs = {}
        for unit in (SERVER, LIVE, OLD, EXITED, "agentkit-job-update.scope"):
            self.scope(unit)
        self.place(1, 0, INIT)
        self.place(100, 1, SERVER)     # the server, adopted by the manager as it started
        self.place(101, 100, LIVE)     # a live pane, which is its harness
        self.place(103, 1, OLD)        # what acme's last harness left, and its child
        self.place(104, 103, OLD)
        self.place(105, 1, EXITED)
        self.panes = "100 0 101\n100 1 102"
        self.stopped = []
        real = host.process_cgroup

        def cgroup(pid="self", cgroup_file=None):
            if pid == "self":
                return real(pid, cgroup_file)
            unit = self.procs.get(pid, (None, None))[1]
            return None if unit is None else f"/{MANAGER}/{unit}" if unit == INIT \
                else f"/{SEATS}/{unit}"

        for target, name, fake in (
                (orch, "user_manager", lambda: True),
                (host, "proc_stat", lambda pid, proc_root=None:
                    host.ProcStat("S", self.procs[pid][0], 1) if pid in self.procs else None),
                (orch, "tmux_out", self.tmux),
                (orch, "stop_scope", lambda scope, log, wait=True:
                    self.stopped.append(scope) or True),
                (host, "process_cgroup", cgroup)):
            patcher = patch.object(target, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def scope(self, unit):
        path = self.root / "cgroup" / SEATS / unit
        path.mkdir(parents=True, exist_ok=True)
        (path / "cgroup.procs").write_text("")

    def place(self, pid, parent, unit):
        """Put that process in that unit, and write the unit's `cgroup.procs` as the kernel would."""
        self.procs[pid] = (parent, unit)
        path = self.root / "cgroup" / SEATS / unit
        if path.is_dir():
            (path / "cgroup.procs").write_text(
                "".join(f"{each}\n" for each, (_, there) in self.procs.items() if there == unit))

    def tmux(self, *args, socket=None, timeout=None, **_kw):
        self.assertEqual(args, ("list-panes", "-a", "-F", "#{pid} #{pane_dead} #{pane_pid}"))
        self.assertIsNotNone(timeout, "a tick's tmux call waits a bounded time")
        self.assertEqual(socket, orch.SOCKET, "only agentkit's own server is asked")
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
        self.place(100, 1, server)
        self.sweep()
        self.assertNotIn(server, self.stopped)
        self.assertEqual(sorted(self.stopped), sorted([OLD, EXITED]))

    def test_a_launch_made_while_the_panes_were_listed_is_not_stopped(self):
        def listing(*args, **kw):
            self.scope(NEW)     # its pane came up after tmux answered
            return 0, self.panes

        with patch.object(orch, "tmux_out", listing):
            self.sweep()
        self.assertNotIn(NEW, self.stopped)
        self.assertEqual(sorted(self.stopped), sorted([OLD, EXITED]))

    def test_a_scope_its_harness_has_not_joined_or_joins_while_tmux_answers_is_not_stopped(self):
        # the manager makes a launch's scope before it moves the harness in
        self.scope(NEW)
        self.sweep()
        self.assertEqual(sorted(self.stopped), sorted([OLD, EXITED]))

        def listing(*args, **kw):
            self.place(106, 100, NEW)
            return 0, self.panes + "\n100 0 106"

        self.stopped.clear()
        with patch.object(orch, "tmux_out", listing):
            self.sweep()
        self.assertEqual(sorted(self.stopped), sorted([OLD, EXITED]))

    def test_a_legacy_seats_harness_on_the_default_server_keeps_its_scope(self):
        self.place(200, 1, "tmux-default.scope")   # the owner's own server, never listed
        self.place(201, 200, OLD)
        self.sweep()
        self.assertEqual(self.stopped, [EXITED])

    def test_a_harness_behind_the_shell_its_pane_runs_keeps_its_scope(self):
        # tmux hands a pane's line to its default shell, and one such as dash forks it
        self.place(300, 100, "tmux-spawn-1.scope")
        self.place(301, 300, OLD)
        self.panes += "\n100 0 300"
        self.sweep()
        self.assertEqual(self.stopped, [EXITED])

    def test_a_scope_with_a_process_or_parent_it_cannot_read_is_kept(self):
        self.place(107, 99, EXITED)    # a parent with no cgroup to read
        self.sweep()
        self.assertEqual(self.stopped, [OLD])
        self.stopped.clear()
        del self.procs[107]            # listed in its scope, but its stat cannot be read
        self.sweep()
        self.assertEqual(self.stopped, [OLD])

    def test_nothing_is_stopped_while_a_harness_cannot_be_proven_gone(self):
        for answer in ((1, "no server running on /tmp/tmux-1000/agentkit"),
                       (0, ""), (0, "100 0 101\nnot a pane line")):
            with self.subTest(answer=answer):
                self.answer = answer
                self.sweep()
                self.assertEqual(self.stopped, [])
        del self.answer
        self.place(101, 1, LIVE)       # a live pane that is not the server's own child
        self.sweep()
        self.assertEqual(self.stopped, [])
        self.place(101, 100, LIVE)
        self.procs[100] = (1, None)    # a server whose cgroup cannot be read
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
