"""A login's ~470-character link, wrapped over the popup's rows, reaches the owner's terminal as
one OSC 8 link: a real tmux under ak's config, a client on a pseudo-terminal, a popup printing it."""

import fcntl
import os
import pty
import re
import select
import shlex
import shutil
import struct
import subprocess
import termios
import time
import unittest

from fixtures.sandbox import Sandbox
from agentkit import orch


class LoginLink(Sandbox):
    def test_the_link_a_login_prints_reaches_the_terminal_whole(self):
        if not shutil.which("tmux"):
            self.skipTest("tmux not installed")
        link = "https://acme.test/oauth/authorize?" + "&".join(f"part{n}=" + "x" * 40 for n in range(10))
        shown = self.root / "link"      # as the harness prints it: the link around its own text
        shown.write_bytes(f"\033]8;;{link}\033\\{link}\033]8;;\033\\\n".encode())
        (sockets := self.root / "s").mkdir()
        env = {**os.environ, "TMUX_TMPDIR": str(sockets), "TERM": "xterm-256color"}
        env.pop("TMUX", None)
        argv = ["tmux", "-S", str(sockets / "t")]
        subprocess.run([*argv, "-f", str(orch.tmux_conf()), "new-session", "-d", "-s", "acme",
                        "-x", "116", "-y", "40", "sleep 60"], env=env, check=True)
        pid, fd = pty.fork()
        if pid == 0:                      # the owner's terminal, attached the way ak attaches it
            try:
                os.execvpe(argv[0], [*argv, "attach-session", "-t", "=acme"], env)
            finally:
                os._exit(127)
        self.addCleanup(os.waitpid, pid, 0)
        self.addCleanup(subprocess.run, [*argv, "kill-server"], env=env, capture_output=True)
        self.addCleanup(os.close, fd)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 116, 0, 0))
        out = bytearray()
        def read_until(found, seconds=20):
            end = time.monotonic() + seconds
            while not found(bytes(out)) and time.monotonic() < end:
                if select.select([fd], [], [], 0.1)[0]:
                    try:
                        out.extend(os.read(fd, 65536))
                    except OSError:
                        break
            return found(bytes(out))
        def clients():
            return subprocess.run([*argv, "list-clients", "-F", "#{client_name}"], env=env,
                                  capture_output=True, text=True).stdout.split()
        self.assertTrue(read_until(lambda _: clients()), "no client attached")
        start = len(out)
        popup = subprocess.Popen([*argv, "display-popup", "-c", clients()[0], "-w", "80%",
                                  "-h", "70%", "-E", f"cat {shlex.quote(str(shown))}; sleep 30"],
                                 env=env)
        self.addCleanup(popup.wait)
        self.addCleanup(popup.kill)       # the popup itself goes with the server
        def links(text):
            return set(re.findall(rb"\x1b\]8;[^;]*;([^\x1b\x07]+)", text[start:]))
        self.assertTrue(read_until(lambda text: link.encode() in links(text)),
                        f"the popup's link reached the terminal as {links(bytes(out))}")


if __name__ == "__main__":
    unittest.main()
