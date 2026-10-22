"""Opening a seat installs ak's PATH shims and starts its harness with them first on its PATH.

A seat's guard lives in the commands its harness runs: its tmux, gh, git, rsync, scp and sftp
are ak's shims in ~/.agentkit/bin, which know the seat by AGENTKIT_SESSION and ask the guard
before the real tool runs.  So a launch puts every shim there before the pane starts, pointing
again a link an older install left at a checkout since moved or at another tool, and starts the
harness with that directory first on its PATH, the opener's PATH behind it, and the seat's name
in its environment and its session's.  A harness that met the real tool first would end or type
into other seats unguarded.  Black-box: `ak orch` opened from a person's terminal
(tests/fixtures/akterm.py), its harness a fake adapter's (tests/fixtures/fakeadapter.py) whose
TUI writes down the environment it started in; this test fails against `/bin/false`.
"""

import json
import os
import shlex
import shutil
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import fakeadapter
from fixtures.akbin import REAL_TMUX, SOCKET, Home
from fixtures.akterm import Terminal

SHIMS = ("gh", "git", "rsync", "scp", "sftp", "tmux")
# The seat's TUI: it writes down the environment it was started in, whole, then idles.
TUI = """{python} -c 'import json, os, sys; print(json.dumps(dict(os.environ)))' >{seen}.tmp
mv {seen}.tmp {seen}
exec sleep 600
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OpenedSeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.dir = home.path / ".agentkit" / "bin"
        cls.dir.mkdir(parents=True)
        # what an older install left: a link into a checkout since moved, one to another tool
        (cls.dir / "tmux").symlink_to(home.root / "moved" / "tools" / "tmux-shim")
        cls.planted = home.root / "planted"
        other = home.root / "other-gh"
        other.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(cls.planted))}\n")
        other.chmod(0o755)
        (cls.dir / "gh").symlink_to(other)
        seen = home.root / "harness.json"
        tui = home.root / "tui.sh"
        tui.write_text(TUI.format(python=shlex.quote(sys.executable),
                                  seen=shlex.quote(str(seen))))
        fakes = fakeadapter.install(home, claude="pass")
        fakes["claude"].answer("interactive", shlex.join(["sh", str(tui)]))
        term = Terminal(home, "orch", "acme", "--model", "opus", "--workers", "opus")
        deadline = time.monotonic() + 60
        while not seen.exists():
            if time.monotonic() > deadline or term.status.exists():
                raise AssertionError(f"seat acme's harness never started; the terminal "
                                     f"shows:\n{term.screen()}")
            time.sleep(0.05)
        cls.harness = json.loads(seen.read_text())

    def test_each_shim_is_in_agentkit_bin_and_can_run(self):
        for name in SHIMS:
            with self.subTest(name):
                shim = self.dir / name
                self.assertTrue(shim.is_file(), f"no {shim}")
                self.assertTrue(os.access(shim, os.X_OK), f"{shim} cannot run")

    def test_a_link_an_older_install_left_reaches_the_real_tool_again(self):
        env = {"PATH": os.pathsep.join([str(self.dir), self.home.env["PATH"]])}
        made = len(self.home.calls("gh"))
        done = self.home.run(str(self.dir / "gh"), "pr", "list", env=env)
        self.assertEqual(self.home.calls("gh")[made:], [["pr", "list"]], done.err)
        self.assertFalse(self.planted.exists())
        done = self.home.run(str(self.dir / "tmux"), "-L", SOCKET, "has-session", "-t", "=acme",
                             env=env)
        self.assertEqual(done.code, 0, done.err)

    def test_the_harness_starts_with_the_shims_first_on_the_opener_s_path(self):
        path = self.harness["PATH"]
        self.assertEqual(path.split(os.pathsep),
                         [str(self.dir), *self.home.env["PATH"].split(os.pathsep)])
        for name in SHIMS:
            with self.subTest(name):
                self.assertEqual(shutil.which(name, path=path), str(self.dir / name))

    def test_the_harness_and_its_session_carry_the_seat_s_name(self):
        self.assertEqual(self.harness.get("AGENTKIT_SESSION"), "acme")
        done = self.home.tmux("show-environment", "-t", "=acme", "AGENTKIT_SESSION")
        self.assertEqual((done.code, done.out), (0, "AGENTKIT_SESSION=acme\n"), done.err)


if __name__ == "__main__":
    unittest.main()
