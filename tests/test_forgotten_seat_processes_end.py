"""What a seat started by hand in a side session ends, wherever it runs, once ak forgets the seat.

Each such process carries the seat's tag (`guard.TMUX_OWNER`); no start of ak's does.  The rows
are processes that outlived their session's close, in a fake /proc (`host.PROC`) of this HOME,
and the tick's sweep (`owner.sweep`) ends them once ak holds no record of the seat and no
session in tmux holds it, or tmux's server has exited.  A pidfd names a row, and a signal through
it acts on the row: KILL ends it, and so does TERM, unless the row is deaf to it (`deaf`).
"""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import config, guard, host, orch, owner, warm  # noqa: E402
from fixtures.clock import Clock  # noqa: E402

GONE = "no server running on /tmp/tmux-1000/agentkit-test"


class ForgottenSeatProcesses(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.proc, state = root / "proc", root / "state"
        self.proc.mkdir()
        state.mkdir()
        stat = host.proc_stat
        self.enterContext(patch.object(host, "PROC", self.proc))
        self.enterContext(patch.object(host, "proc_stat", lambda pid: stat(pid, self.proc)))
        self.enterContext(patch.dict(os.environ, {"HOME": "/home/acme"}))
        self.enterContext(patch.object(config, "STATE", state))
        self.enterContext(patch.object(os, "pidfd_open", self.pidfd_open))
        self.enterContext(patch.object(signal, "pidfd_send_signal", self.send))
        self.enterContext(patch.object(orch, "tmux_out", self.tmux))
        self.enterContext(patch.object(orch, "sessions", lambda: self.seats))
        self.rows, self.held, self.sent, self.log, self.fds = {}, {"beta", "dev"}, set(), [], {}
        self.said, self.seats = None, []   # tmux's refusal, else its listing; the seats it holds
        self.put("self", None, comm="python3")

    def tmux(self, *args, **_kw):
        self.assertEqual(args[0], "list-sessions")
        return (1, self.said) if self.said else (0, "\n".join(self.held))

    def record(self, name, data=None):
        config.session_path(name).write_text(json.dumps(data or {}))

    def put(self, pid, tag="gone", *, ppid=1, comm="sleep", deaf=False, **env):
        self.rows[pid] = deaf
        row = self.proc / str(pid)
        row.mkdir(exist_ok=True)
        (row / "stat").write_text(f"{pid} ({comm}) S {ppid} {pid} 300{' 0' * 15} 1")
        (row / "comm").write_text(f"{comm}\n")
        (row / "cmdline").write_text(f"sleep\0{pid}\0")
        env = {"HOME": "/home/acme", **({guard.TMUX_OWNER: tag} if tag else {}), **env}
        (row / "environ").write_text("".join(f"{key}={value}\0" for key, value in env.items()))

    def pidfd_open(self, pid):
        held = os.open(os.devnull, os.O_RDONLY)
        self.fds[held] = pid
        return held

    def send(self, held, number):
        pid = self.fds[held]
        self.sent.add((number.name.removeprefix("SIG"), pid))
        if number == signal.SIGKILL or not self.rows[pid]:
            shutil.rmtree(self.proc / str(pid))

    def sweep(self, meanwhile=lambda: None):
        """One sweep, as the tick runs it; `meanwhile` happens during its grace."""
        with patch.object(owner, "time", Clock(lambda _: meanwhile())):
            owner.sweep(self.log.append)

    def running(self):
        return {int(row.name) for row in self.proc.iterdir() if row.name.isdigit()}

    def test_a_forgotten_seat_s_processes_end_deaf_to_term_or_out_of_the_pane_s_tree(self):
        self.put(20, comm="tmux: server")     # a server a tagged pane started
        self.put(10, ppid=20)
        self.put(11, deaf=True)
        self.sweep()
        self.assertEqual(self.sent, {("TERM", 10), ("TERM", 11), ("KILL", 11)})
        self.assertEqual(self.running(), {20})
        self.assertEqual(set(self.log), {f"{sent} to sleep {pid} (pid {pid}), which a forgotten "
                                         f"seat `gone` left running" for sent, pid in self.sent})

    def test_a_seat_ak_holds_keeps_them_until_it_forgets_it_renamed_or_not(self):
        for tag, names in (("acme", ("acme",)), ("old", ("old", "new"))):
            with self.subTest(tag=tag):
                self.record("old", {"renamed": "new"})
                self.record("new")
                self.record("acme")
                self.put(10, tag)
                self.sweep()
                self.assertEqual(self.running(), {10})
                for name in names:
                    config.session_path(name).unlink()
                self.sweep()
                self.assertEqual(self.running(), set())

    def test_once_ak_s_tmux_server_holds_no_session_a_seat_with_no_record_is_forgotten(self):
        self.seats = [{"name": "legacy"}]   # one on the owner's own server
        self.record("acme")
        # exited, or holding the Go port's control session alone
        for said, held in ((GONE, set()), (None, {orch.CONTROL})):
            with self.subTest(said=said, held=held):
                self.said, self.held = said, held
                for pid, tag in enumerate(("gone", "acme", "legacy"), 10):
                    self.put(pid, tag)
                self.sweep()
                self.assertEqual(self.running(), {11, 12})

    def test_what_is_not_a_forgotten_seat_s_runs_on(self):
        self.put(10, "beta")                            # a seat tmux holds
        self.put(11, None)
        self.put(12, HOME="/home/elsewhere")
        self.put(13, AGENTKIT_RUN="/runs/fix-api")
        self.sweep()
        self.said = "error connecting to /tmp/tmux-1000/agentkit-test (Permission denied)"
        self.put(14)                                    # a failed probe proves no seat gone
        self.sweep()
        self.assertEqual((self.running(), self.sent, self.log), (set(range(10, 15)), set(), []))

    def test_one_whose_seat_comes_back_in_the_grace_gets_no_kill(self):
        self.put(10, deaf=True)
        self.sweep(lambda: self.record("gone"))
        self.assertEqual((self.sent, self.running()), ({("TERM", 10)}, {10}))

    def test_what_an_ak_in_the_side_session_starts_carries_no_tag(self):
        os.environ[guard.TMUX_OWNER] = "gone"
        owner.mark("ak run")
        self.assertNotIn(guard.TMUX_OWNER, os.environ)
        self.put(os.getpid(), None)
        self.put(10, None, **{owner.MARK: os.environ[owner.MARK]})   # the `ak`'s, still running
        self.sweep()
        self.assertEqual(self.running(), {os.getpid(), 10})
        os.environ[guard.TMUX_OWNER] = "gone"
        self.assertNotIn(guard.TMUX_OWNER, owner.unmarked())
        self.assertIsNone(orch.seat_env("acme", "agentkit-test")[guard.TMUX_OWNER])  # -r: panes
        self.assertIn(f"{guard.TMUX_OWNER}=", orch.job_env())     # blanks what a server holds
        with patch.object(warm.os, "posix_spawn") as spawn:
            warm._start(str(REPO))
        self.assertNotIn(guard.TMUX_OWNER, spawn.call_args.args[2])

    def test_what_marks_itself_drops_the_tag_from_its_own_proc_and_keeps_its_input(self):
        # /proc shows the environment a process started with, which is what the tick reads; a
        # seat's hook hands its helper the owner's words before that helper marks itself
        said = ("import sys; from agentkit import owner; said = sys.stdin.read(); "
                "owner.mark('seat look'); print(open('/proc/self/environ').read().split('\\0')"
                f".count('{guard.TMUX_OWNER}=gone'), said)")
        done = subprocess.run([sys.executable, "-c", said], cwd=REPO, input="continue",
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ, guard.TMUX_OWNER: "gone"})
        self.assertEqual(done.stdout.split(), ["0", "continue"], done.stderr)


if __name__ == "__main__":
    unittest.main()
