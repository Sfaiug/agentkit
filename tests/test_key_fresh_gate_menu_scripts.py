"""The fresh-install gate's menu scripts run through the menu as it draws now.

tests/e2e-fresh.sh drives the menu through a pty with scripts it writes, but it runs only when a
harness is upgraded, so a menu change that broke them reached nobody until then (#1685, and
again with #1802 and #1807).  Here every `.exp` script the gate writes runs, in the gate's order,
through the gate's own `ptydrive.py` and words (its single-quoted `MENU`, `PROMPT`, `NODIALOG`,
...), on the terminal and command of its `drive` line, all read out of the gate and never copied:
`menu1` makes the seat through `n`, its name, Tab and Enter, reaches the prompt and detaches;
`menu2` attaches it under `TERM=xterm-ghostty`; `phone` lands in the menu; `menu3` stops the seat
from its popup, leaving no tmux session for it.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, its seat a fake claude of tests/fixtures/fakeadapter.py
whose pane draws Claude's ready prompt.
"""

import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, REAL_TMUX, REPO, Home
from fixtures.akseat import FIXTURES, PANE

GATE = (REPO / "tests" / "e2e-fresh.sh").read_text()
DRIVER = re.search(r"""cat >"\$WORK/ptydrive.py" <<'PY'\n(.*?\n)PY\n""", GATE, re.S)[1]
WORDS = "\n".join(re.findall(r"^[A-Z]+='[^']*'.*$", GATE, re.M))
SCRIPTS = dict(re.findall(r'cat >"\$WORK/(\w+)\.exp" <<EXP\n(.*?\n)EXP\n', GATE, re.S))
DRIVES = re.findall(r"^\s*drive (\w+) (\S+) (.*)$", GATE, re.M)
SEAT = re.findall(r"^\s*SEAT=(\w+)$", GATE, re.M)[-1]
# What the phone key's forced command is; the gate reads it from the line install.sh writes.
FORCED = "ak attach"


def script(body):
    """A script as the gate's unquoted heredoc writes it: its words and the seat's name in."""
    done = subprocess.run(["bash", "-c", f"{WORDS}\ncat <<EXP\n{body}EXP\n"],
                          env={"SEAT": SEAT}, capture_output=True, text=True, check=True)
    return done.stdout


def sessions(home, name):
    """The tmux sessions ak's server holds once `name` has run; after menu3, once the seat it
    stops in a process of its own is gone, or a minute on."""
    deadline = time.monotonic() + 60
    while True:
        held = home.tmux("list-sessions", "-F", "#{session_name}").out.split()
        if name != "menu3" or SEAT not in held or time.monotonic() > deadline:
            return held
        time.sleep(0.1)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class GateScripts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        screen, typed = home.root / "pane.txt", home.root / "pane.typed"
        shutil.copy(FIXTURES / "claude-prompt-pane.txt", screen)
        fakeadapter.install(home, claude="pass")["claude"].answer(
            "interactive", shlex.join([sys.executable, str(PANE), str(screen), str(typed)]))
        gate = home.root / "gate"
        gate.mkdir()
        (gate / "ptydrive.py").write_text(DRIVER)
        cls.ran, cls.sessions, session = {}, {}, ""
        for name, term, command in DRIVES:
            (gate / f"{name}.exp").write_text(script(SCRIPTS[name]))
            argv = shlex.split(command.replace("$FORCED", FORCED))
            cls.ran[name] = home.run(
                sys.executable, str(gate / "ptydrive.py"), str(gate / f"{name}.txt"),
                str(gate / f"{name}.exp"), "--", AK, *argv[1:], timeout=600,
                env={"TERM": term, "AGENTKIT_SESSION": session})
            cls.sessions[name] = sessions(home, name)
            session = SEAT    # the gate's drive names the seat once menu1 has made it

    def passed(self, name):
        done = self.ran[name]
        self.assertEqual(done.code, 0, f"{done.out}{done.err}")

    def test_the_gate_drives_every_script_it_writes(self):
        self.assertEqual(sorted(name for name, _, _ in DRIVES), sorted(SCRIPTS))
        self.assertEqual(sorted(SCRIPTS), ["menu1", "menu2", "menu3", "phone"])

    def test_menu1_makes_the_seat_reaches_its_prompt_and_detaches(self):
        self.passed("menu1")
        self.assertIn(SEAT, self.sessions["menu1"])

    def test_menu2_attaches_the_seat_under_ghostty(self):
        self.assertIn(("menu2", "xterm-ghostty"), [drive[:2] for drive in DRIVES])
        self.passed("menu2")

    def test_phone_lands_in_the_menu(self):
        self.passed("phone")

    def test_menu3_stops_the_seat_from_its_popup(self):
        self.passed("menu3")
        self.assertNotIn(SEAT, self.sessions["menu3"])


if __name__ == "__main__":
    unittest.main()
