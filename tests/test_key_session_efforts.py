"""Each seat runs at its own efforts, and changing the defaults moves no live session.

A seat's record holds its models' effort keys under `efforts`, and its runs run at them, their
receipts saying so.  A record from before runs at the efforts its entries give it, and keeps
them once a fresh window's `c` changes an entry, also where config.toml has no model tables
and the shipped config's answer.  Black-box: `AK_BIN` on a gitrig.py project, akseat.py seats,
an akterm.py terminal and fakeadapter.py harnesses, judged by the effort each turn is handed.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from fixtures.gitrig import Rig


def run_in(test, seat, title):
    """`ak run` of a new task in `seat`: its receipt, and the effort each Claude turn got."""
    home, fake = test.home, test.fakes["claude"]
    before, turns = set(taskfile.runs(home)), len(fake.runs())
    done = home.ak("run", str(taskfile.write(home, test.rig.path, title)), "--no-merge",
                   env={"AGENTKIT_SESSION": seat}, timeout=300)
    test.assertEqual(done.code, 0, done.out + done.err)
    [run_dir] = set(taskfile.runs(home)) - before
    return (json.loads((run_dir / "run.json").read_text()),
            {run["argv"][1] for run in fake.runs()[turns:]})


class TwoSeatsOnOneModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="pass")
        for effort in ("high", "max"):
            Seat(cls.home, f"acme-{effort}", cwd=cls.rig.path, alive=False, planned=True,
                 record={"reviewers": ["astra"], "efforts": {"opus": {"effort": effort}}})

    def test_each_seat_s_run_builds_at_that_seat_s_effort(self):
        for effort in ("high", "max"):
            with self.subTest(effort=effort):
                receipt, handed = run_in(self, f"acme-{effort}", f"Build at {effort}")
                self.assertEqual(handed, {effort})
                self.assertEqual(receipt["efforts"]["opus"], {"effort": effort})


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatsFromBefore(unittest.TestCase):
    """Fable is `xhigh` in the shipped config, and a step on `c` takes it to `max`."""

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "widgets")
        self.fakes = fakeadapter.install(self.home, claude="work", codex="pass")
        for name in ("atoll-ran", "atoll-new"):
            Seat(self.home, name, model="fable", cwd=self.rig.path, alive=False, planned=True,
                 record={"reviewers": ["astra"]})

    def step_fable(self):
        """Enter on Fable's effort on a fresh window's `c`, waited on until saved."""
        config = self.home.path / ".agentkit/config.toml"
        term = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("c config")
        term.keys("c")
        term.wait("› Fable 5.1")
        before = config.read_bytes()
        term.keys("Right", "Right", "Right", "Enter")      # onto the effort, and a step
        deadline = time.monotonic() + 30
        while config.read_bytes() == before:
            self.assertLess(time.monotonic(), deadline, "the step was never saved")
            time.sleep(0.05)
        self.assertEqual(akconfig.read(self.home)["models"]["fable"]["effort"], "max")

    def keeps_its_effort(self):
        self.assertEqual(run_in(self, "atoll-ran", "Build before")[1], {"xhigh"})
        self.step_fable()
        self.assertEqual(run_in(self, "atoll-ran", "Build after")[1], {"xhigh"})
        self.assertEqual(run_in(self, "atoll-new", "Build first after")[1], {"xhigh"})

    def test_with_model_tables(self):
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"})
        self.keeps_its_effort()

    def test_with_no_model_tables(self):
        (self.home.path / ".agentkit/config.toml").write_text("# no tables: the shipped config\n")
        self.keeps_its_effort()


if __name__ == "__main__":
    unittest.main()
