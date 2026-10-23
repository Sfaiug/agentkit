"""A new seat starts from config.toml's [defaults], and a config.toml with no models uses the
shipped ones.

[defaults] is what the next seat starts with: the last created seat's orchestrator, workers and
reviewers.  A seat opened without naming reviewers takes the ones [defaults] lists into its own
record, and the file keeps them beside the orchestrator and workers that seat was given.  An
install from before the models moved into config.toml left only `max_runs` there: such a file
configures no models, so the shipped config.default.toml answers for them, while `max_runs`
is still the home file's, and the first seat made writes the shipped models into it, keeping
`max_runs`.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, under a terminal where it opens a seat, with harnesses from
fakeadapter.py on the Home's own tmux.
"""

import json
import re
import sys
from pathlib import Path
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home

SHIPPED = tomllib.loads(akconfig.SHIPPED_CONFIG.read_text())
OLD = "max_runs = 2\n"     # all an install from before the models moved left in config.toml


def record(home, seat):
    path = home.path / ".agentkit" / "state" / f"session-{seat}.json"
    return json.loads(path.read_text()) if path.is_file() else {}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class DefaultReviewers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        path = akconfig.write(cls.home, {"one": "codex", "two": "claude"}, orchestrator="one",
                              workers=["one"])
        path.write_text(path.read_text().replace("[defaults]\n",
                                                 '[defaults]\nreviewers = ["two"]\n', 1))
        fakeadapter.install(cls.home, claude="pass", codex="pass")
        cls.done = cls.home.ak("orch", "demo", "--model", "two", "--workers", "one", tty=True)

    def test_the_seat_opens_and_its_record_carries_the_default_reviewers(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(self.home.tmux("has-session", "-t", "=demo").code, 0)
        seat = record(self.home, "demo")
        self.assertEqual({key: seat.get(key) for key in ("orchestrator", "workers", "reviewers")},
                         {"orchestrator": "two", "workers": ["one"], "reviewers": ["two"]})

    def test_the_defaults_keep_the_reviewers_beside_the_seat_s_own_choices(self):
        self.assertEqual(akconfig.read(self.home)["defaults"],
                         {"orchestrator": "two", "workers": ["one"], "reviewers": ["two"]})


class ConfigWithoutModels(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.config = self.home.write(".agentkit/config.toml", OLD)

    def test_a_model_the_shipped_config_lacks_is_refused_naming_the_shipped_ones(self):
        done = self.home.ak("orch", "demo", "--model", "two", "--dry-run")
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertRegex(done.err, r"\btwo\b")
        for name in SHIPPED["models"]:
            with self.subTest(name):
                self.assertRegex(done.err, rf"(?<![\w-]){re.escape(name)}(?![\w-])")
        self.assertEqual(self.config.read_text(), OLD)

    def test_a_shipped_model_plans_a_seat_with_the_shipped_workers(self):
        done = self.home.ak("orch", "demo", "--model", "opus", "--dry-run")
        self.assertEqual(done.code, 0, done.out + done.err)
        workers = " ".join(SHIPPED["defaults"]["workers"])
        self.assertIn(f"workers {workers}", done.out.splitlines())
        self.assertEqual(self.config.read_text(), OLD)

    def test_max_runs_is_still_the_home_file_s(self):
        done = self.home.ak("run", "status", env={"AK_MAX_RUNS": None})
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("at most 2 runs at once", done.out.splitlines()[0])

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_the_first_seat_writes_the_shipped_models_and_keeps_max_runs(self):
        fakeadapter.install(self.home, claude="pass")
        # Enter takes the workers the seat is offered
        done = self.home.ak("orch", "demo", "--model", "opus", tty=True, input="\r")
        self.assertEqual(done.code, 0, done.out + done.err)
        written = akconfig.read(self.home)
        self.assertEqual(written["max_runs"], 2)
        self.assertEqual(written["models"], SHIPPED["models"])
        self.assertEqual(written["defaults"], {"orchestrator": "opus",
                                               "workers": SHIPPED["defaults"]["workers"]})


if __name__ == "__main__":
    unittest.main()
