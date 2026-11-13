"""A follow-up with no check joins another run's open fix at its site, and only there.

A finding older than the task becomes a follow-up; one proven by a command that cannot be a
plan check, with backticks, has no command to name its fix run by, so its site does: the whole
`path:line`.  A later run's follow-up at the site of a fix run still open is that run's work and
starts none; one at another file starts its own, though that path ends as the first one's does
past a star in a name.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, from a seat of akseat.py, against the origin of gitrig.py and the
GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_followup_plan_line import alive, held, wait_for

ALPHA, BETA = "alpha*/api.py:1", "beta*/api.py:1"


def finding(site, what):
    """A finding at `site` whose proof fails on base too, with backticks: no plan check."""
    path = site.rpartition(":")[0]
    return ["finding", site, what, "callers get stale data",
            "--run", f"test \"`cat '{path}'`\" = fixed"]


def title(directory):
    """What the fix run in `directory` fixes: its task's heading."""
    return (directory / "task.md").read_text().split("\n# ", 1)[1].split("\n", 1)[0]


def work(name):
    return {"write": {name: "added\n"}, "commit": f"add {name}",
            "final": f"## Summary\nadded {name}", "hand_in": [["done"]]}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AFollowUpJoinsAnOpenFixOnlyAtItsSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets", files={"alpha*/api.py": "old\n", "beta*/api.py": "old\n"})
        GitHub(cls.home).grant(rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        Seat(cls.home, "acme", cwd=rig.path, record={"reviewers": ["astra"]}, planned=True)
        cls.release = cls.home.root / "adapters" / "release"
        # Every fix run's turn waits for the test, so the first run's is open for the second.
        hold = held(cls.release, fakeadapter.PASS)
        fakes = fakeadapter.install(cls.home, claude=[work("a.txt"), hold, work("b.txt"), hold],
                                    codex=[{"final": "A defect older than the task.", "hand_in": [
                                               finding(ALPHA, "the alpha api is old"), ["done"]]},
                                           {"final": "The same defect, and another.", "hand_in": [
                                               finding(ALPHA, "the alpha api still reads old"),
                                               finding(BETA, "the beta api is old"), ["done"]]},
                                           "pass"])
        cls.addClassCleanup(cls.settle)
        cls.ran = []
        for name in ("a.txt", "b.txt"):
            before = set(taskfile.runs(cls.home))
            task = taskfile.write(cls.home, rig.path, f"Add {name}", done_when=(f"test -f {name}",))
            done = cls.home.ak("run", str(task), env={"AGENTKIT_SESSION": "acme"}, timeout=600)
            # the fix run this merge started has taken its turn before the next run reviews
            wait_for(lambda: fakes["claude"].n >= 2 * len(cls.ran) + 2, 120)
            parent, *fixes = sorted(set(taskfile.runs(cls.home)) - before)
            cls.ran.append((done, json.loads((parent / "run.json").read_text()), fixes))

    @classmethod
    def settle(cls):
        # A fix run still going would outlive this Home, so each ends before the Home goes.
        cls.release.write_text("")
        for *_, fixes in cls.ran:
            for directory in fixes:
                if not wait_for(lambda: not alive(json.loads((directory / "run.json").read_text()).get("pid")), 60):
                    cls.home.ak("run", "stop", directory.name)

    def test_both_runs_merge(self):
        for done, parent, _ in self.ran:
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual((parent["state"], parent["merged"]), ("pass", True))

    def test_the_first_run_s_follow_up_starts_a_fix_run(self):
        (_, parent, fixes), _ = self.ran
        self.assertEqual(len(fixes), 1, fixes)
        self.assertEqual(parent.get("followup_runs"), [fixes[0].name])
        self.assertTrue(title(fixes[0]).startswith(f"Fix {ALPHA} - "), title(fixes[0]))

    def test_the_later_run_starts_one_fix_run_for_the_other_site_alone(self):
        _, (_, parent, fixes) = self.ran
        self.assertEqual(len(fixes), 1, fixes)
        self.assertEqual(parent.get("followup_runs"), [fixes[0].name])
        self.assertTrue(title(fixes[0]).startswith(f"Fix {BETA} - "), title(fixes[0]))


if __name__ == "__main__":
    unittest.main()
