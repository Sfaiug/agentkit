"""A seat's harness runs in a terminal of the pane's size, both ways, and its exit is the seat's.

The line a harness's adapter prints for `ak orch` runs the harness inside a wrapper of ak's,
which watches the seat's screen; the owner must not notice it is there.  So the harness sees a
terminal exactly as large as the pane, what it prints reaches the pane, what the owner types
reaches the harness, and when it exits the line exits with its code.

Black-box: the adapters beside the program `AK_BIN` names (or `AK_ROOT`'s) print the line, with
the environment `orch.command` hands them, and it runs as printed, its wrapper included, in a
pseudo-terminal of the test's own, with a fake harness first on PATH under the harness's own
name.  No tmux: outside a seat's pane the wrapper names nothing and looks at nothing.  This
test fails against `/bin/false`.
"""

import fcntl
import json
import os
from pathlib import Path
import select
import shlex
import signal
import struct
import subprocess
import sys
import termios
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import ROOT

# Each harness's adapter, its program's own name, and a model and effort for it.
HARNESSES = {"claude": ("claude", "claude-acme-7", "low"),
             "grokbuild": ("grok", "grok-acme-4", "high")}
LINES, COLUMNS = 37, 101    # the pane's size: no terminal's default
READY = "acme harness ready"
TYPED = "fix the api"
EXIT = 7                    # an exit code ak never uses
# Says it is ready, takes one line, and keeps that line and the size of its terminal then: by
# the time a typed line arrives, any wrapper has given its terminal the pane's size.
FAKE = """#!{python}
import json, os, sys
print({ready!r}, flush=True)
line = sys.stdin.readline()
size = os.get_terminal_size(0)
with open({part!r}, "w") as out:
    json.dump({{"lines": size.lines, "columns": size.columns, "line": line}}, out)
os.replace({part!r}, {saw!r})
sys.exit({exit})
"""


class ASeatsHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.cwd = home.path / "code" / "acme"
        cls.cwd.mkdir(parents=True)
        cls.ran = {harness: cls.relay(harness, *spec) for harness, spec in HARNESSES.items()}

    @classmethod
    def relay(cls, harness, program, model, effort):
        """Run the seat's line in a terminal of the pane's size, type a line once the harness
        is ready, and return what it saw, what reached the terminal, and the line's exit code."""
        home = cls.home
        saw = home.root / f"{program}-saw.json"
        home.fake(program, FAKE.format(python=sys.executable, ready=READY, exit=EXIT,
                                       saw=str(saw), part=f"{saw}.part"))
        # what `orch.command` hands the verb, and the seat's name `ak orch` runs it under
        told = {"AGENTKIT_SESSION": "acme", "AGENTKIT_ACCOUNT": "",
                "AGENTKIT_RULEBOOK": str(home.write("rb.md", "rb\n")),
                "AGENTKIT_FIRST_PROMPT": "", "AGENTKIT_CLAUDE_CHECKED": "1"}
        printed = home.run("bash", str(ROOT / "adapters" / f"{harness}.sh"), "interactive",
                           model, effort, env=told, cwd=cls.cwd)
        assert printed.code == 0 and printed.out.strip(), (harness, printed.err)
        pane, terminal = os.openpty()
        fcntl.ioctl(terminal, termios.TIOCSWINSZ, struct.pack("HHHH", LINES, COLUMNS, 0, 0))
        try:
            proc = subprocess.Popen(
                shlex.split(printed.out), stdin=terminal, stdout=terminal, stderr=terminal,
                env={**home.env, **told}, cwd=cls.cwd, start_new_session=True,
                preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
        finally:
            os.close(terminal)
        shown, typed, deadline = b"", False, time.monotonic() + 120
        try:
            while True:
                assert time.monotonic() < deadline, (harness, shown.decode(errors="replace"))
                if select.select([pane], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(pane, 65536)
                    except OSError:     # every end of the terminal closed: the line is over
                        chunk = b""
                    if not chunk:
                        break
                    shown += chunk
                elif proc.poll() is not None:
                    break
                if not typed and READY.encode() in shown:
                    os.write(pane, f"{TYPED}\r".encode())   # the Enter key
                    typed = True
            code = proc.wait(timeout=30)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            os.close(pane)
        return (json.loads(saw.read_text()) if saw.exists() else {}), shown, code

    def test_the_harness_sees_a_terminal_of_the_pane_s_size(self):
        for harness, (saw, _, _) in self.ran.items():
            with self.subTest(harness=harness):
                self.assertEqual((saw.get("lines"), saw.get("columns")), (LINES, COLUMNS))

    def test_what_the_harness_prints_reaches_the_pane(self):
        for harness, (_, shown, _) in self.ran.items():
            with self.subTest(harness=harness):
                self.assertIn(READY.encode(), shown)

    def test_a_line_typed_in_the_pane_reaches_the_harness(self):
        for harness, (saw, _, _) in self.ran.items():
            with self.subTest(harness=harness):
                self.assertEqual(saw.get("line"), f"{TYPED}\n")

    def test_the_harness_s_exit_code_is_the_line_s(self):
        for harness, (_, _, code) in self.ran.items():
            with self.subTest(harness=harness):
                self.assertEqual(code, EXIT)


if __name__ == "__main__":
    unittest.main()
