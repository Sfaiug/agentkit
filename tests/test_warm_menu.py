"""`Ctrl-b m`'s menu, warm (`agentkit/warm.py`).

With a server up, the popup's menu is the server's fork on the popup's terminal, the popup still
the client, which forwards it signals and ends with its code.  With none, the client runs
`bin/ak` and starts a server only where an install is stamped.  A server leaves once an install
is newer than its code, for the one it starts.  Each test has a HOME of its own, a tmux with no
server up and an invented socket; each server is stopped by taking its socket away.
"""

import fcntl
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import warm

WARM = REPO / "agentkit" / "warm.py"
KEYS = b"stop this session"   # on the overlay's key line: its menu is up


class Home:
    """A HOME of its own, stamped as an install's or not, and the servers that came up in it."""

    def __init__(self, case, stamped=True):
        home = tempfile.TemporaryDirectory(prefix="warm-")
        case.addCleanup(home.cleanup)
        self.case, self.root, self.started = case, Path(home.name), []
        self.state = self.root / ".agentkit" / "state"
        self.state.mkdir(parents=True)
        tmux = self.root / "bin" / "tmux"
        tmux.parent.mkdir()
        tmux.write_text("#!/bin/sh\necho 'no server running on acme-warm' >&2\nexit 1\n")
        tmux.chmod(0o755)
        self.stamp = self.state / "installed-at"     # what an install leaves, and when
        if stamped:
            self.stamp.write_text(str(time.time()))
        self.env = {"HOME": str(self.root), "PATH": f"{tmux.parent}{os.pathsep}{os.defpath}",
                    "AGENTKIT_TMUX_SOCKET": "acme-warm", "TERM": "xterm-256color",
                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}
        name = warm.place(str(REPO))[1]
        self.socket, self.lock = self.state / f"{name}.sock", self.state / f"{name}.lock"
        case.addCleanup(self.stop)

    def serve(self):
        self.started.append(subprocess.Popen([sys.executable, str(WARM), "serve"], env=self.env,
                                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, start_new_session=True))
        self.up()
        return self.started[-1]

    def up(self):
        deadline = time.monotonic() + 60
        while not self.socket.exists():
            self.case.assertLess(time.monotonic(), deadline, "no server came up")
            time.sleep(0.02)

    def popup(self):
        """`Ctrl-b m`'s command on a terminal of its own, drawn up to its key line: (the
        client, the terminal's other end)."""
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 90, 0, 0))
        client = subprocess.Popen([sys.executable, "-S", "-I", str(WARM), "attach", "--overlay"],
                                  stdin=slave, stdout=slave, stderr=slave, env=self.env,
                                  start_new_session=True)
        os.close(slave)
        self.case.addCleanup(os.close, master)
        self.case.addCleanup(lambda: client.poll() is None and client.kill())
        drawn, deadline = b"", time.monotonic() + 60
        while KEYS not in drawn:
            self.case.assertLess(time.monotonic(), deadline, f"never drawn: {drawn[-2000:]!r}")
            if select.select([master], [], [], 0.1)[0]:
                drawn += os.read(master, 65536)
        return client, master

    def stop(self):
        """Every server here gone: each leaves once its socket is not there."""
        deadline = time.monotonic() + 60
        while True:
            self.socket.unlink(missing_ok=True)
            try:
                with open(self.lock, "a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                self.case.assertLess(time.monotonic(), deadline, "a server stayed up")
                time.sleep(0.05)
        for server in self.started:
            server.wait(30)


class Served(unittest.TestCase):
    def test_the_popup_s_menu_is_the_server_s_fork_and_its_code_the_popup_s(self):
        home = Home(self)
        home.serve()
        for end, code in ((b"\x1b", 0), (signal.SIGTERM, 128 + signal.SIGTERM)):
            with self.subTest(end=end):
                client, master = home.popup()
                # drawn, and still itself: a cold popup would be `bin/ak` by now
                self.assertIn(str(WARM).encode(),
                              Path(f"/proc/{client.pid}/cmdline").read_bytes().split(b"\0"))
                if isinstance(end, bytes):
                    os.write(master, end)
                else:
                    client.send_signal(end)     # what its terminal sends, the menu's to hear
                self.assertEqual(client.wait(60), code)

    def test_a_server_whose_install_moved_leaves_for_one_on_the_new_code(self):
        home = Home(self)
        server = home.serve()
        home.stamp.write_text(str(time.time()))
        self.assertEqual(server.wait(60), 0)
        home.up()                               # the one it started


class Cold(unittest.TestCase):
    def test_with_no_server_bin_ak_runs_and_a_server_starts_only_where_an_install_is(self):
        for stamped in (False, True):
            with self.subTest(stamped=stamped):
                home = Home(self, stamped)
                with patch.object(warm, "_start") as start, \
                        patch.object(warm.os, "execv", side_effect=SystemExit) as execv:
                    with self.assertRaises(SystemExit):
                        warm.cold(str(REPO), ["nonsense"], str(home.state))
                self.assertEqual(start.call_count, stamped)
                self.assertEqual(execv.call_args.args[1][1:],
                                 [str(REPO / "bin" / "ak"), "nonsense"])
        ran = subprocess.run([sys.executable, "-S", "-I", str(WARM), "nonsense"], env=home.env,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(ran.returncode, 2)
        self.assertIn("unknown subcommand 'nonsense'", ran.stderr)
        home.up()                               # for the next popup


if __name__ == "__main__":
    unittest.main()
