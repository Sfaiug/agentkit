"""A seat's own PR of documents alone is reviewed before it lands, like any change.

The owner decided on 24 Oct 2026: "Yes, review everything".  Files that steer models were
counted as documents, so a model could rewrite them with no second model looking.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, from the seat of
akseat.py, against the bare origin of gitrig.py and the GitHub of fakegh.py, with scripted
harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


class DocumentsAreReviewed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """The acme seat, whose orchestrator is opus, reviews its own PR changing README.md
        alone, with astra reviewing."""
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", files={"AGENTS.md": "---\ntests: true\n---\n# widgets\n",
                                                   "README.md": "# widgets\n"})
        cls.gh = GitHub(cls.home)
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="pass", codex="pass")
        Seat(cls.home, "acme", cwd=cls.rig.path, alive=False,
             record={"workers": ["opus", "astra"]}, planned=True)
        cls.head = cls.rig.branch("readme", {"README.md": "# widgets\n\nSay what it is.\n"})
        cls.url = cls.gh.open_pr(cls.rig, "readme", title="Say what widgets is")
        cls.done = cls.home.ak("run", "--review-pr", cls.url, env={"AGENTKIT_SESSION": "acme"},
                               cwd=cls.rig.path, timeout=300)
        cls.state = json.loads((taskfile.only_run(cls.home) / "run.json").read_text())

    def test_another_model_reviews_the_head(self):
        self.assertEqual([turn["role"] for turn in self.fakes["codex"].runs()], ["reviewer"])
        self.assertEqual([review["commit"]["oid"] for review in self.gh.pr(1)["reviews"]],
                         [self.head])

    def test_it_lands_once_reviewed(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))
        self.assertEqual(self.gh.pr(1)["merge"]["head"], self.head)


if __name__ == "__main__":
    unittest.main()
