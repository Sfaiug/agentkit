"""A click on an amber meter hands the terminal to that login's `login again`, and the ak screen
is back, the login asked again, as soon as it ends; a click on any other meter does nothing.

`menu.loop` runs in a child process on a pty of its own, with a temporary HOME holding the
usage and login readings, the seat listing faked, and a fake Claude adapter that stands in for
the sign-in: it reads one line, as a pasted code, and then answers with a login 30 days out.
Nothing here starts a session, a tmux server, a probe or a real login.
"""

import fcntl
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import terminal

CHILD = r"""
import os, sys
sys.path.insert(0, os.environ["LOGIN_CLICK_REPO"])
from agentkit import config, menu, orch
orch.listing = lambda reconcile=True: [{"name": "seat-a", "repo": None, "path": "/", "created": 0}]
orch.job_notices = lambda: []
menu.seat_row_state = lambda cfg, session, **facts: {"word": "working", "reason": "", "since": None}
menu.Live.probe = lambda self, now=None: False
menu.usage.collect = lambda cfg, **kwargs: {}
sys.exit(menu.loop(config.load(), dry_run=True))
"""

ADAPTER = r"""#!/usr/bin/env bash
case "$*" in
  "login again")
    echo "<signing in as ${AGENTKIT_ACCOUNT:-default}>"
    read -r code
    echo "{\"email\":\"owner@acme.test\",\"ends\":$(( $(date +%s) + 30 * 86400 ))}" >"$FAKE/answer"
    echo "<signed in with $code>" ;;
  login-end) cat "$FAKE/answer" ;;
  *) exit 2 ;;
esac
"""


class LoginClick(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix=".ak-test-login-click-")
        self.addCleanup(home.cleanup)
        self.home = Path(home.name)
        state, fake = self.home / ".agentkit/state", self.home / "fake"
        state.mkdir(parents=True)
        fake.mkdir()
        (fake / "claude.sh").write_text(ADAPTER)
        (fake / "claude.sh").chmod(0o755)
        now = time.time()
        week = {"name": "weekly", "resets_at": now + 3 * 86400, "window_secs": 604800, "used": 50}
        (state / "usage.json").write_text(json.dumps({"fetched_at": now, "providers": {
            "anthropic": {"meters": [week]}}}))
        soon = {"email": "owner@acme.test", "ends": int(now) + 2 * 86400}
        (fake / "answer").write_text(json.dumps(soon))
        self.logins = state / "logins.json"
        self.logins.write_text(json.dumps({"anthropic": {"default": {**soon, "checked_at": now}}}))
        self.master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 100, 0, 0))
        env = {key: value for key, value in os.environ.items()
               if key not in ("NO_COLOR", "COLUMNS", "LINES", "TMUX")}
        env.update({"HOME": str(self.home), "TERM": "xterm-256color", "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                    "AGENTKIT_ADAPTER_DIR": str(fake), "FAKE": str(fake),
                    "LOGIN_CLICK_REPO": str(REPO)})
        self.proc = subprocess.Popen([sys.executable, "-c", CHILD], stdin=slave, stdout=slave,
                                     stderr=slave, env=env, start_new_session=True)
        os.close(slave)
        self.output, self.lock = b"", threading.Lock()
        reader = threading.Thread(target=self.read, daemon=True)
        reader.start()

        def close():
            if self.proc.poll() is None:
                self.proc.kill()          # this test's own child, and nothing else
            self.proc.wait(10)
            os.close(self.master)
            reader.join(5)
        self.addCleanup(close)

    def read(self):
        while True:
            try:
                chunk = os.read(self.master, 4096)
            except OSError:
                return
            if not chunk:
                return
            with self.lock:
                self.output += chunk

    def text(self):
        with self.lock:
            return self.output.decode("utf-8", "replace")

    def until(self, ready, what, after=0):
        deadline = time.monotonic() + 15
        while not ready(self.text()[after:]):
            self.assertLess(time.monotonic(), deadline,
                            f"timed out waiting for {what}:\n{self.text()[-3000:]!r}")
            time.sleep(0.02)

    def frame(self, after=0):
        """The lines of the last whole menu drawn after `after`, row 1 first."""
        found = []

        def ready(text):
            for part in reversed(text.split("\x1b[H")[1:]):
                lines = [terminal.ANSI.sub("", line).rstrip("\r")
                         for line in part.split("\x1b[J")[0].split("\n")[:-1]]
                if "\x1b[J" in part and any("esc leave" in line for line in lines):
                    found[:] = lines
                    return True
            return False
        self.until(ready, "a drawn menu", after)
        return found

    def click(self, lines, label):
        row, line = next((number, line) for number, line in enumerate(lines, 1)
                         if f"{label} " in line and ("% left" in line or "—" in line))
        col = line.index(label) + 2
        os.write(self.master, f"\x1b[<0;{col};{row}M".encode())
        os.write(self.master, f"\x1b[<0;{col};{row}m".encode())

    def test_a_click_on_the_amber_meter_signs_in_and_comes_back(self):
        lines = self.frame()
        self.click(lines, "MiMo")         # grey: no login of it ends soon
        self.click(lines, "Claude")       # amber: its login ends in 2 days
        self.until(lambda text: "<signing in as default>" in text, "the sign-in")
        os.write(self.master, b"abc\r")   # the owner pastes the code the sign-in asks for
        self.until(lambda text: "<signed in with abc>" in text, "the sign-in to end")
        self.frame(after=self.text().index("<signed in"))    # the ak screen is back by itself
        ends = json.loads(self.logins.read_text())["anthropic"]["default"]["ends"]
        self.assertGreater(ends, time.time() + 29 * 86400)
        self.assertEqual(self.text().count("<signing in"), 1)
        os.write(self.master, b"\x1b")
        self.assertEqual(self.proc.wait(15), 0, self.text()[-3000:])


if __name__ == "__main__":
    unittest.main()
