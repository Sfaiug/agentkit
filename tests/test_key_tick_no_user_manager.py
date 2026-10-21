"""Without a user systemd manager, `ak watch` asks no host service tool and writes no unit.

A Mac, a container and a host without systemd have no `systemctl --user` to answer, and there a
tick still runs every pass and exits 0: the ended-login pass is skipped even on a server
`install.sh` stamped, and nothing is installed as a unit.  A session bus address, a bus that is
anybody's and a manager's socket left behind are no manager.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, and this test fails against
`/bin/false`.
"""

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, REPO, Home

SERVICE = ("systemctl", "systemd-run", "loginctl", "journalctl")
# What the tick started is waited out inside the box, so nothing of it outlives the test.
LAST = r"""
import os, subprocess, sys, time
code = subprocess.call(sys.argv[1:])
deadline = time.monotonic() + 60
while time.monotonic() < deadline:
    if not [p for p in os.listdir("/proc") if p.isdigit() and int(p) not in (1, os.getpid())]:
        sys.exit(code)
    time.sleep(0.1)
sys.exit("the tick left processes running")
"""


def boxable():
    if not shutil.which("bwrap"):
        return False
    return subprocess.run(["bwrap", "--dev-bind", "/", "/", "--unshare-net", "--unshare-pid",
                           "--proc", "/proc", "--tmpfs", "/tmp", "--", "true"],
                          capture_output=True, timeout=60).returncode == 0


def tick(home, env=None):
    """One `ak watch`, boxed: a tick asks the public boards and the shared browser on loopback,
    so it gets a loopback of its own, and a /tmp holding only this Home and the program."""
    keep = {home.root, home.tmux_dir, REPO, Path(AK).resolve().parent}
    binds = [arg for path in sorted(map(str, keep), key=len) if Path(path).is_relative_to("/tmp")
             for arg in ("--bind", path, path)]
    return home.run("bwrap", "--dev-bind", "/", "/", "--unshare-net", "--unshare-pid",
                    "--proc", "/proc", "--tmpfs", "/tmp", *binds, "--",
                    sys.executable, "-c", LAST, AK, "watch", env=env)


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class NoUserManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        config = home.path / ".agentkit" / "config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        # a collection on record from just now: what a due one does is test_key_gc_scheduled's
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        home.write(".agentkit/state/installed-at", f"{int(time.time())}\n")
        cls.runtime = home.root / "run"

    def ticked_alone(self):
        for name in SERVICE:
            self.home.log(name).unlink(missing_ok=True)
        done = tick(self.home, env={"DBUS_SESSION_BUS_ADDRESS": f"unix:path={self.runtime}/bus"})
        self.assertEqual(done.code, 0, done.err)
        for name in SERVICE:
            self.assertEqual(self.home.calls(name), [], name)
        self.assertFalse((self.home.path / ".config" / "systemd").exists())

    def test_a_tick_with_an_empty_runtime_directory_asks_no_service_tool(self):
        self.assertEqual(list(self.runtime.iterdir()), [])
        self.ticked_alone()

    def test_a_bus_anybody_listens_on_and_a_manager_socket_left_behind_are_no_manager(self):
        (self.runtime / "systemd").mkdir()
        gone = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        gone.bind(str(self.runtime / "systemd" / "private"))
        gone.close()
        bus = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(bus.close)
        bus.bind(str(self.runtime / "bus"))
        bus.listen()
        try:
            self.ticked_alone()
        finally:
            for path in (self.runtime / "systemd" / "private", self.runtime / "bus"):
                path.unlink(missing_ok=True)
            os.rmdir(self.runtime / "systemd")


if __name__ == "__main__":
    unittest.main()
