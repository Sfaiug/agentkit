"""What a maintainer decides on a PR ak opened on someone else's repository goes back to its seat.

Without push rights a run ends at a PR from a fork, waiting for the maintainer, and from then on
the tick follows that PR for the seat that launched the run: a request for changes and a close
without a merge are recorded on the run and typed into the seat at its prompt, for it to act on;
a merge is recorded on the run and typed into no seat, which owes nothing for it; an approval is
news for nobody.  Each is said once, however many ticks follow.  Black-box: the program `AK_BIN`
names runs `ak run` and `ak watch` from outside through tests/fixtures/akbin.py, against the bare
origins of gitrig.py and the GitHub of fakegh.py, where the viewer `acme` may only read
`zeta/gadgets`, with scripted harnesses from fakeadapter.py and a seat of akseat.py; this test
fails against `/bin/false`.
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

# The tick asks the public boards over HTTP: a proxy nobody answers keeps it off the network.
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
SLUG = "zeta/gadgets"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MaintainerDecides(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        home.env.update(OFFLINE)
        rig, cls.gh = Rig(home, "gadgets", owner="zeta"), GitHub(home)
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex="pass")
        cls.seat = Seat(home, "acme", cwd=rig.path, record={"repo": str(rig.path)})
        cls.launched = [home.ak("run", str(taskfile.write(home, rig.path, title)),
                                env={"AGENTKIT_SESSION": "acme"}, timeout=300)
                        for title in ("Add retry file", "Add retry note")]
        cls.runs = taskfile.runs(home)
        cls.changed, cls.approved = (cls.gh.pr(n, SLUG)["url"] for n in (1, 2))
        cls.told = [cls.seat.lines()]
        cls.gh.edit(1, SLUG, reviewDecision="CHANGES_REQUESTED")
        cls.gh.edit(2, SLUG, reviewDecision="APPROVED")
        cls.ticks = [home.ak("watch"), home.ak("watch")]
        cls.told += [cls.seat.lines()]
        cls.records = [cls.record()]
        cls.gh.edit(1, SLUG, state="CLOSED")
        merged = home.run("gh", "pr", "merge", "2", "--repo", SLUG, "--squash")
        assert merged.code == 0, merged.err
        cls.ticks += [home.ak("watch"), home.ak("watch")]
        cls.told += [cls.seat.lines()]
        cls.records += [cls.record()]

    @classmethod
    def record(cls):
        return [json.loads((run / "run.json").read_text()) for run in cls.runs]

    def setUp(self):
        for done in self.launched:
            self.assertEqual(done.code, 0, done.out + done.err)
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.out + done.err)

    def new(self, step):
        """The lines typed into the seat in that step, not before it."""
        return self.told[step][len(self.told[step - 1]):]

    def test_both_runs_ended_waiting_for_the_maintainer_on_prs_from_a_fork(self):
        self.assertEqual([(state["pr"], state["merged"]) for state in self.records[0]],
                         [(self.changed, False), (self.approved, False)])
        self.assertEqual([len(lines) for lines in self.told], [2, 3, 4])

    def test_a_request_for_changes_is_recorded_and_typed_into_the_seat_once(self):
        line, = self.new(1)
        self.assertIn(self.changed, line)
        self.assertIn("requested changes", line)
        self.assertIn("requested changes", self.records[0][0]["merge_note"])

    def test_an_approval_is_news_for_nobody(self):
        self.assertEqual(self.records[0][1]["merge_note"], "waiting for the maintainer")
        self.assertNotIn(self.approved, " ".join(self.new(1)))

    def test_a_close_without_a_merge_is_recorded_and_typed_into_the_seat_once(self):
        line, = self.new(2)
        self.assertIn(self.changed, line)
        self.assertIn("closed", line)
        self.assertIn("closed", self.records[1][0]["merge_note"])
        self.assertFalse(self.records[1][0]["merged"])

    def test_a_merge_is_recorded_on_its_run_and_typed_into_no_seat(self):
        state = self.records[1][1]
        self.assertTrue(state["merged"])
        self.assertIn("merged", state["merge_note"])
        self.assertNotIn(self.approved, " ".join(self.new(1) + self.new(2)))
        self.assertIn(state["merge_note"], (self.runs[1] / "result.md").read_text())


if __name__ == "__main__":
    unittest.main()
