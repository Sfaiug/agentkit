"""A click on an amber meter hands the terminal to that login's `login again`, and the ak screen
is back as soon as it ends, its meter grey; a click on a grey one signs nothing in.  `menu.loop`
in-process, its keys scripted, with a fake Claude adapter whose `login again` makes a login 30
days out.  The link the login prints reaches the owner's terminal whole: a real tmux under ak's
own config, a client attached to it on a pseudo-terminal, and the popup Ctrl-b m opens.
"""

from contextlib import redirect_stdout
import fcntl
import io
import json
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import sys
import termios
import time
import unittest
from unittest.mock import Mock, patch

from fixtures.sandbox import Sandbox
from fixtures.subscriptions import number
from agentkit import config, menu, orch, terminal

DAY = 86400
WEEK = {"name": "weekly", "resets_at": 10000 + 3 * DAY, "window_secs": 604800, "used": 50}
ADAPTER = r"""#!/usr/bin/env bash
case "$*" in
  "login again") echo "again ${AGENTKIT_ACCOUNT:-default}" >>"$FAKE/calls"
                 cp "$FAKE/renewed" "$FAKE/standing" ;;
  login-end) cat "$FAKE/standing" ;;
  *) exit 2 ;;
esac
"""


class LoginClick(Sandbox):
    def setUp(self):
        super().setUp()
        self.fake = self.root / "fake"
        self.fake.mkdir()
        (self.fake / "claude.sh").write_text(ADAPTER)
        (self.fake / "claude.sh").chmod(0o755)
        soon = {"email": "owner@acme.test", "ends": 10000 + 2 * DAY}
        (self.fake / "standing").write_text(json.dumps(soon))
        (self.fake / "renewed").write_text(json.dumps({**soon, "ends": 10000 + 30 * DAY}))
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000, "providers": {
            "anthropic": {"meters": [WEEK]}, "openai": {"meters": [WEEK]}}}))
        (config.STATE / "logins.json").write_text(json.dumps(
            {"anthropic": {"default": {**soon, "checked_at": 10000}}}))
        self.stack.enter_context(patch.dict(os.environ, {
            "FAKE": str(self.fake), config.ADAPTER_DIR_ENV: str(self.fake)}))
        for target, name, value in ((menu.orch, "listing", []), (menu.orch, "job_notices", []),
                                    (menu.Live, "probe", False), (sys.stdin, "isatty", True)):
            self.stack.enter_context(patch.object(target, name, return_value=value))
        self.stack.enter_context(patch.object(menu.usage, "collect", return_value={}))
        for target, name in ((menu.Live, "watch"), (terminal, "sense")):
            self.stack.enter_context(patch.object(target, name))
        self.stack.enter_context(patch.object(terminal, "Keyboard",
                                              return_value=Mock(**{"take.return_value": True})))
        self.stack.enter_context(patch.object(terminal, "width", return_value=100))

    def click(self, drawn, label):
        """A click on the middle of `label`'s cell in the grid as `drawn`."""
        cell = ("usage", number(self.cfg, label))
        return next(terminal.Key("click", col=(first + last) // 2, row=row)
                    for row, (_, places) in drawn["spots"].items()
                    for first, last, at in places if at == cell)

    def test_a_click_on_the_amber_meter_signs_in_and_comes_back(self):
        draws = []
        real = menu.draw

        def draw(*args, **kwargs):
            draws.append(args[5])         # what the screen drew, read back as the loop does
            return real(*args, **kwargs)
        script = iter([lambda: self.click(draws[-1], "ChatGPT"),   # grey: no login ends soon
                       lambda: self.click(draws[-1], "Claude"),    # amber: it ends in 2 days
                       lambda: terminal.Key("esc")])
        with patch.object(menu, "draw", side_effect=draw), \
                patch.object(menu, "moving", side_effect=lambda *a, **k: next(script)()), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        calls = self.fake / "calls"
        self.assertEqual(calls.read_text() if calls.exists() else "", "again default\n")
        self.assertEqual(len(draws), 3)   # the screen came back by itself before Esc left it
        self.assertEqual(draws[-1]["logins"], {})     # ... and drew no amber meter: no tick ran
        kept = json.loads((config.STATE / "logins.json").read_text())["anthropic"]["default"]
        self.assertEqual(kept["ends"], 10000 + 30 * DAY)
        self.assertFalse(any(menu.login_notes(menu.usage_rows(self.cfg))))

    def test_a_login_that_failed_leaves_its_meter_amber(self):
        (self.fake / "claude.sh").write_text(ADAPTER.replace(
            'cp "$FAKE/renewed" "$FAKE/standing" ;;', 'exit 1 ;;'))
        draws = []
        real = menu.draw

        def draw(*args, **kwargs):
            draws.append(args[5])
            return real(*args, **kwargs)
        script = iter([lambda: self.click(draws[-1], "Claude"), lambda: terminal.Key("esc")])
        with patch.object(menu, "draw", side_effect=draw), patch.object(menu, "pause"), \
                patch.object(menu, "moving", side_effect=lambda *a, **k: next(script)()), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        self.assertEqual(list(draws[-1]["logins"].values()), [("anthropic", None)])

    def test_the_link_a_login_prints_reaches_the_terminal_whole(self):
        """Claude's sign-in link is some 470 characters: in the popup it wraps over rows between
        borders, and only the OSC 8 link around them makes them one thing to click."""
        if not shutil.which("tmux"):
            self.skipTest("tmux not installed")
        link = "https://acme.test/oauth/authorize?" + "&".join(f"part{n}=" + "x" * 40 for n in range(10))
        shown = self.root / "link"      # as the harness prints it: the link around its own text
        shown.write_bytes(f"\033]8;;{link}\033\\{link}\033]8;;\033\\\n".encode())
        sockets = self.root / "s"
        sockets.mkdir()
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
        clients = lambda: subprocess.run([*argv, "list-clients", "-F", "#{client_name}"], env=env,
                                         capture_output=True, text=True).stdout.split()
        self.assertTrue(read_until(lambda _: clients()), "no client attached")
        start = len(out)
        popup = subprocess.Popen([*argv, "display-popup", "-c", clients()[0], "-w", "80%",
                                  "-h", "70%", "-E", f"cat {shown}; sleep 30"], env=env)
        self.addCleanup(popup.wait)
        self.addCleanup(popup.kill)       # the popup itself goes with the server
        links = lambda text: set(re.findall(rb"\x1b\]8;[^;]*;([^\x1b\x07]+)", text[start:]))
        self.assertTrue(read_until(lambda text: link.encode() in links(text)),
                        f"the popup's link reached the terminal as {links(bytes(out))}")


if __name__ == "__main__":
    unittest.main()
