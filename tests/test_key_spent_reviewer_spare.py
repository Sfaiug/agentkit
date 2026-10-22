"""A reviewer whose provider says its usage is spent is replaced by a spare, and its provider sits
out the next hour.

A spent account is not a broken one: the work must still get its review, from a configured
model on another provider, and nothing should be sent to the spent provider again until its
window could have reset.  The log says who refused, until when, and who took the review, so a
person reading it knows why the reviewer they expected is not the one in result.md.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py, with scripted harnesses from fakeadapter.py whose codex says its usage
limit is hit.
"""

from datetime import datetime, timezone
import json
import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

REFUSED = re.compile(r"WARN reviewer astra refused: You have hit your usage limit\.; "
                     r"nothing is picked on openai until (\d{4}-\d\d-\d\d \d\d:\d\d)$")
FELL_BACK = "WARN reviewer fell back to spark"


class SpentReviewer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra", "spark"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="dead", muse="pass")
        cls.before = time.time()
        cls.done = cls.home.ak("run", str(taskfile.write(cls.home, cls.rig.path)), "--no-merge",
                               timeout=300)
        cls.after = time.time()
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.log = (cls.run_dir / "log.txt").read_text().splitlines()
        cls.calls = {harness: fake.n for harness, fake in cls.fakes.items()}
        # a second run in the same hour, after the first has finished
        task = taskfile.write(cls.home, cls.rig.path, "Add retry note")
        cls.again = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.again_dir = taskfile.runs(cls.home)[-1]

    def test_the_review_goes_to_the_spare_and_the_run_passes(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual({key: self.state.get(key) for key in ("state", "verdict", "reviewer")},
                         {"state": "pass", "verdict": "PASS", "reviewer": "spark"})
        self.assertEqual({key: self.state["review"][key] for key in (
            "reviewer", "reviewer_provider", "verdict")}, {
            "reviewer": "spark", "reviewer_provider": "meta", "verdict": "PASS"})
        self.assertEqual(self.calls, {"claude": 1, "codex": 1, "muse": 1})
        spent, spare = self.fakes["codex"].runs()[0], self.fakes["muse"].runs()[0]
        self.assertEqual((spent["role"], spent["argv"][0]),
                         ("reviewer", akconfig.SHIPPED["astra"]["model"]))
        self.assertEqual((spare["role"], spare["argv"][0]),
                         ("reviewer", akconfig.SHIPPED["spark"]["model"]))
        self.assertEqual(spare["hand_ins"][-1]["code"], 0, spare["hand_ins"])

    def test_the_log_says_who_refused_and_who_took_the_review(self):
        refused = [i for i, line in enumerate(self.log) if REFUSED.search(line)]
        fell = [i for i, line in enumerate(self.log) if line.endswith(FELL_BACK)]
        self.assertEqual((len(refused), len(fell)), (1, 1), "\n".join(self.log))
        self.assertLess(refused[0], fell[0])

    def test_the_spent_provider_sits_out_one_hour_from_the_refusal(self):
        line = next(line for line in self.log if REFUSED.search(line))
        until = datetime.strptime(REFUSED.search(line).group(1), "%Y-%m-%d %H:%M")
        until = until.replace(tzinfo=timezone.utc).timestamp()
        # printed to the minute, an hour after a refusal that came during the run
        self.assertLessEqual(until, self.after + 3600)
        self.assertGreater(until + 60, self.before + 3600)

    def test_result_md_names_the_reviewer_that_reviewed(self):
        lines = (self.run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[0], "# PASS, not merged: --no-merge — Add retry file")
        named = [line for line in lines if line.startswith("executor:")]
        self.assertEqual(len(named), 1, lines)
        self.assertRegex(named[0], r"^executor: opus\s+reviewer: spark$")

    def test_a_run_within_the_hour_never_asks_the_spent_provider(self):
        self.assertEqual(self.again.code, 0, self.again.out + self.again.err)
        self.assertNotEqual(self.again_dir, self.run_dir)
        state = json.loads((self.again_dir / "run.json").read_text())
        self.assertEqual({key: state.get(key) for key in ("verdict", "executor", "reviewer")},
                         {"verdict": "PASS", "executor": "opus", "reviewer": "spark"})
        self.assertEqual({harness: fake.n for harness, fake in self.fakes.items()},
                         {"claude": 2, "codex": 1, "muse": 2})
        log = (self.again_dir / "log.txt").read_text().splitlines()
        self.assertFalse([line for line in log if line.endswith(FELL_BACK)], log)


if __name__ == "__main__":
    unittest.main()
