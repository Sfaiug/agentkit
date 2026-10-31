"""On `c` and on a project's Features screen, Space changes the highlighted mark or effort in
place and Enter opens: Enter on a mark or an effort, and Space on `Models`, do nothing.

The owner's rule (27 Oct 2026, `terminal.keys`): "everywhere enter is for like opening, new page
and stuff like that, and space should be select / unselect".  Each key line names Space and
Enter only where they act.  A key sent after another is read after it, so Enter then Space
moving a thing exactly one step proves Enter left it alone.  Black-box: the program `AK_BIN`
names, in a person's terminal (tests/fixtures/akterm.py), its harnesses the fakes of
tests/fixtures/fakeadapter.py and the features command a script of the test's logging every
call; this test fails against `/bin/false`.  The terminal has no colour (NO_COLOR).
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

TAIL = "r recommended   a apply to all sessions   esc back"
MARK_KEYS = f"  ↑↓←→ move   ␣ mark   {TAIL}"
STEP_KEYS = f"  ↑↓←→ move   ␣ step   {TAIL}"
OPEN_KEYS = f"  ↑↓←→ move   ⏎ open   {TAIL}"
FEATURE_KEYS = "  ↑↓←→ move   ␣ mark   esc back"
FAKE = """#!{python}
import json, sys
from pathlib import Path
here = Path(__file__).parent
with open(here / "calls.log", "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
rows = json.loads((here / "features.json").read_text())
if sys.argv[1] == "list":
    print(json.dumps(rows))
else:
    feature, who, value = sys.argv[2:]
    row = next(row for row in rows if row["id"] == feature)
    row[who] = value == "on"
    (here / "features.json").write_text(json.dumps(rows))
    print(json.dumps(row))
"""


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


def shows(text, keys):
    """A screen with `text` over that key line, judged at once: tmux may be read part way
    through a draw, the row drawn and the key line not yet."""
    return lambda screen: text in screen and key_line(screen) == keys


def until(test):
    deadline = time.monotonic() + 30
    while not test():
        assert time.monotonic() < deadline, "never came"
        time.sleep(0.05)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ConfigKeys(unittest.TestCase):
    """New seats' marks: fable orchestrates, fable and astra build."""

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": {"harness": "claude", "effort": "xhigh"},
                                   "astra": {"harness": "codex", "effort": "high"}})
        self.term = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1"})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(shows("› Fable 5.1", MARK_KEYS))

    def test_space_flips_a_builds_mark_and_enter_leaves_it(self):
        self.term.keys("Right", "Right")
        self.term.wait(shows("› Fable 5.1     ●  ▰▰▰▰▱   xhigh   [■]", MARK_KEYS))
        self.term.keys("Enter", "Space")
        self.term.wait("› Fable 5.1     ●  ▰▰▰▰▱   xhigh   [□]")
        until(lambda: akconfig.read(self.home)["defaults"]["workers"] == ["astra"])

    def test_space_steps_an_effort_once_and_enter_leaves_it(self):
        self.term.keys("Right", "Right", "Right")
        self.term.wait(lambda screen: key_line(screen) == STEP_KEYS)
        self.term.keys("Enter", "Space")
        self.term.wait("xhigh    ■  ▰▰▰▰▰   max ")
        until(lambda: akconfig.read(self.home)["models"]["fable"].get("exec_effort") == "max")

    def test_space_on_models_does_nothing_and_enter_opens_it(self):
        self.term.keys("j", "j")
        self.term.wait(shows("› Models", OPEN_KEYS))
        self.term.keys("Space", "j")      # still on `c`: the highlight moves on from Models
        self.term.wait("› Subscriptions")
        self.term.keys("k", "Enter")
        self.term.wait(lambda screen: screen.startswith("agentkit · config · models"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class FeaturesKeys(unittest.TestCase):
    def test_space_flips_you_through_set_and_enter_calls_none(self):
        home = Home()
        self.addCleanup(home.close)
        acme = home.path / "code" / "ACME"
        acme.mkdir(parents=True)
        assert home.run("git", "init", "-q", str(acme)).code == 0
        fake = home.write("acme-features/features.py", FAKE.format(python=sys.executable))
        fake.chmod(0o755)
        home.write("acme-features/features.json",
                   [{"id": "dark", "name": "Dark mode", "you": False, "everyone": False}])
        home.write("code/ACME/AGENTS.md", f"---\nfeatures: {fake}\n---\n\n# ACME\n")
        Seat(home, "acme-fix", cwd=acme, record={"repo": str(acme)})
        term = Terminal(home, size=(100, 30), env={"NO_COLOR": "1"})
        term.wait("hidden feature")
        term.keys("k")
        term.wait("› ACME")
        term.keys("Enter")
        term.wait(shows("› Dark mode  [○]", FEATURE_KEYS))
        term.keys("Enter", "Space")
        term.wait("› Dark mode  [●]")
        calls = [json.loads(line) for line in
                 (home.path / "acme-features/calls.log").read_text().splitlines()]
        self.assertEqual([call for call in calls if call != ["list"]],
                         [["set", "dark", "you", "on"]])


if __name__ == "__main__":
    unittest.main()
