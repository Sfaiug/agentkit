"""What a gone `ak` left running in its session, the tick's sweep ends; nothing else.

The processes are rows of a fake /proc (`host.PROC`), its `self` the `ak` that marks itself with
`owner.mark`, in session SESSION.  A pidfd names a row, and a signal through it acts on the row:
KILL ends it, and so does TERM, unless the row `turns` at TERM into the one given.
"""

import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import host, owner  # noqa: E402
from fixtures.clock import Clock  # noqa: E402

AK, SESSION = os.getpid(), 300   # the `ak`'s pid, as `owner.mark` reads it, and its session
# each way a process the sweep would end is one it never ends: a service's own session, a tmux
# server, a run, another HOME, a mark from another pid namespace
KEPT = ({"session": 20}, {"comm": "tmux: server"}, {"AGENTKIT_RUN": "/runs/fix-api"},
        {"HOME": "/home/elsewhere"}, {"namespace": 1})


class GoneAkLeftovers(unittest.TestCase):
    def setUp(self):
        self.proc = Path(self.enterContext(tempfile.TemporaryDirectory()))
        stat = host.proc_stat
        self.enterContext(patch.object(host, "PROC", self.proc))
        self.enterContext(patch.object(host, "proc_stat", lambda pid: stat(pid, self.proc)))
        self.enterContext(patch.dict(os.environ, {"HOME": "/home/acme"}))
        self.enterContext(patch.object(os, "pidfd_open", self.pidfd_open))
        self.enterContext(patch.object(signal, "pidfd_send_signal", self.send))
        self.rows, self.held, self.sent, self.log, self.reused = {}, {}, set(), [], set()
        self.mark = self.marked()

    def marked(self, namespace=None):
        """The mark `owner.mark` makes as `ak usage`, in another pid namespace if one is given."""
        self.put("self")
        with patch.object(owner, "_namespace", return_value=namespace or owner._namespace()):
            owner.mark("ak usage")
        return os.environ[owner.MARK]

    def put(self, pid, mark=None, *, start=1, session=SESSION, ppid=1, comm="sleep", turns=None,
            namespace=None, **env):
        """A row of the fake /proc, its mark made in another pid namespace if one is given."""
        self.rows[pid] = (dict(mark=mark, start=start, session=session, ppid=ppid, comm=comm,
                               **env), turns)
        row = self.proc / str(pid)
        row.mkdir(exist_ok=True)
        (row / "stat").write_text(f"{pid} ({comm}) S {ppid} {pid} {session}{' 0' * 15} {start}")
        (row / "comm").write_text(f"{comm}\n")
        (row / "cmdline").write_text(f"sleep\0{pid}\0")
        mark = self.marked(namespace) if namespace else mark
        env = {"HOME": "/home/acme", **({owner.MARK: mark} if mark else {}), **env}
        (row / "environ").write_text("".join(f"{key}={value}\0" for key, value in env.items()))

    def pidfd_open(self, pid):
        if pid in self.reused:      # given to another process since the look
            self.put(pid, self.mark, start=2)
        held = os.open(os.devnull, os.O_RDONLY)
        self.held[held] = pid
        return held

    def send(self, held, number):
        pid = self.held[held]
        self.sent.add((number.name.removeprefix("SIG"), pid))
        row, turns = self.rows[pid]
        if number == signal.SIGTERM and turns is not None:
            self.put(pid, **{**row, **turns})
        else:
            shutil.rmtree(self.proc / str(pid))

    def sweep(self):
        """One sweep, as the tick runs it; the seconds of each grace it waited out."""
        waits = []
        with patch.object(owner, "time", Clock(waits.append)):
            owner.sweep(self.log.append)
        return waits

    def running(self):
        return {int(row.name) for row in self.proc.iterdir() if row.name.isdigit()}

    def test_what_a_gone_ak_left_in_its_session_ends_though_deaf_to_term(self):
        self.put(10, self.mark)
        self.put(11, self.mark, turns={})
        self.assertEqual(self.sweep(), [owner.GRACE])
        self.assertEqual(self.sent, {("TERM", 10), ("TERM", 11), ("KILL", 11)})
        self.assertEqual(self.running(), set())
        self.assertEqual(set(self.log), {f"{sent} to sleep {pid} (pid {pid}), which a gone "
                                         f"`ak usage` (pid {AK}) left running"
                                         for sent, pid in self.sent})

    def test_one_whose_ak_pid_now_names_another_process_ends(self):
        self.put(AK, start=2)
        self.put(10, self.mark)
        self.sweep()
        self.assertEqual(self.running(), {AK})

    def test_what_a_running_ak_left_runs_on(self):
        self.put(AK)
        self.put(10, self.mark)
        self.assertEqual(self.sweep(), [])
        self.assertEqual(self.running(), {AK, 10})

    def test_what_the_sweep_never_ends_runs_on_and_no_grace_is_waited_out(self):
        for pid, kept in enumerate(KEPT, 20):
            self.put(pid, self.mark, **kept)
        self.put(25, self.mark, session=20, ppid=20)    # in the service's session
        self.put(26, self.mark, ppid=21)                # below the tmux server
        self.assertEqual(self.sweep(), [])
        self.assertEqual((self.sent, self.log), (set(), []))
        self.assertEqual(self.running(), set(range(20, 27)))

    def test_one_turned_by_the_second_look_into_one_the_sweep_never_ends_gets_no_kill(self):
        for pid, kept in enumerate((*KEPT, {}), 30):
            self.put(pid, self.mark, turns=kept)
        self.assertEqual(self.sweep(), [owner.GRACE])
        self.assertEqual(self.sent, {*(("TERM", pid) for pid in range(30, 36)), ("KILL", 35)})
        self.assertEqual(self.running(), set(range(30, 35)))

    def test_a_pid_given_to_another_process_since_the_look_gets_no_signal(self):
        self.put(10, self.mark)
        self.reused = {10}
        self.assertEqual(self.sweep(), [])
        self.assertEqual(self.sent, set())

    def test_a_loop_of_parents_read_across_a_pid_given_anew_ends_the_sweep(self):
        self.put(10, self.mark, ppid=20)
        self.put(20, self.mark, ppid=10)
        sweep = threading.Thread(target=self.sweep, daemon=True)
        sweep.start()
        sweep.join(60)
        self.assertFalse(sweep.is_alive(), "the sweep walked the loop for good")
        self.assertEqual(self.running(), set())


if __name__ == "__main__":
    unittest.main()
