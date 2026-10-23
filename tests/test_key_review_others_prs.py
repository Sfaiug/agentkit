"""The tick reviews other people's open PRs on the owner's repositories, once for each head.

Someone else's pull request on a repository this account owns gets ak's review without anyone
asking: each tick lists the open PRs of every checkout under ~/code whose repository the
account owns and starts a review of each head not yet reviewed, its verdict posted on GitHub on
that commit and a pass offered to the inbox seat to merge at that very commit.  A head already
reviewed is never reviewed again, even once the tick has lost its own note of it and only
GitHub still holds the review; a push is a new head, and is reviewed anew.  The account's own
PRs, drafts, and repositories somebody else owns are left alone.  Black-box: the program
`AK_BIN` names runs `ak watch` from outside through tests/fixtures/akbin.py, against the bare
origins of gitrig.py and the GitHub of fakegh.py, with a scripted reviewer from fakeadapter.py;
this test fails against `/bin/false`.
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
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# The tick asks the public boards over HTTP: a proxy nobody answers keeps it off the network.
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
ENDED = ("pass", "fail", "error")


def tick(home):
    done = home.ak("watch")
    assert done.code == 0, done.out + done.err


def ended(home, count, bound=120):
    """The runs' records once `count` runs have ended: a tick starts a review detached."""
    deadline = time.monotonic() + bound
    while True:
        states = []
        for run in taskfile.runs(home):
            try:
                states.append(json.loads((run / "run.json").read_text()))
            except (FileNotFoundError, ValueError):
                states.append({})
        if len(states) >= count and all(state.get("state") in ENDED for state in states):
            return states
        if time.monotonic() > deadline:
            raise AssertionError(f"{count} ended runs expected, found {states}")
        time.sleep(0.2)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ReviewedOncePerHead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        home.env.update(OFFLINE)
        cls.gh = gh = GitHub(home)
        rig, other = Rig(home, "widgets"), Rig(home, "gadgets", owner="zeta")
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="pass", codex="pass")
        # where a pass is offered for merging; with no inbox open, ak opens one itself
        cls.inbox = Seat(home, "inbox")
        cls.first = rig.branch("fix-api", {"api.py": "x = 2\n"})
        cls.url = gh.open_pr(rig, "fix-api", title="Fix api", author="beta")
        rig.branch("own-docs", {"docs.md": "ours\n"})
        gh.open_pr(rig, "own-docs", title="Own docs")
        rig.branch("wip", {"wip.txt": "later\n"})
        gh.open_pr(rig, "wip", title="Work in progress", author="beta")
        gh.edit(3, rig.slug, isDraft=True)
        other.branch("fix-ui", {"ui.py": "y = 1\n"})
        gh.open_pr(other, "fix-ui", title="Fix ui", author="beta")
        tick(home)
        cls.reviewed = ended(home, 1)
        tick(home)
        cls.again = len(taskfile.runs(home))
        (home.path / ".agentkit" / "state" / "watch.json").unlink()
        tick(home)
        cls.forgotten = len(taskfile.runs(home))
        cls.noted = json.loads((home.path / ".agentkit/state/watch.json").read_text())
        rig.git("checkout", "-q", "fix-api")
        cls.second = rig.commit({"api.py": "x = 3\n"}, "fix api again")
        rig.git("checkout", "-q", "main")
        tick(home)
        cls.pushed = ended(home, 2)

    def reviews(self, number=1, slug="acme/widgets"):
        """Who posted each review GitHub holds on the PR, on which commit, and its first line."""
        return [(review["author"]["login"], review["commit"]["oid"],
                 review["body"].split("\n", 1)[0])
                for review in self.gh.pr(number, slug)["reviews"]]

    def test_another_persons_open_pr_on_the_owners_repository_is_reviewed_on_github(self):
        self.assertEqual([state.get("review_pr") for state in self.reviewed], [self.url])
        login, commit, first = self.reviews()[0]
        self.assertEqual((login, commit), ("acme", self.first))
        self.assertTrue(first.startswith(f"agentkit review of {self.first[:12]} "), first)

    def test_a_passing_review_asks_the_inbox_to_merge_at_the_reviewed_commit(self):
        line = self.inbox.wait_lines(1)[0]
        self.assertIn(self.url, line)
        self.assertIn(f"--match-head-commit {self.first}", line)

    def test_the_owners_own_prs_drafts_and_others_repositories_are_not_reviewed(self):
        self.assertEqual((self.reviews(2), self.reviews(3), self.reviews(1, "zeta/gadgets")),
                         ([], [], []))
        self.assertEqual(len(self.pushed), 2)

    def test_a_head_already_reviewed_is_not_reviewed_again(self):
        self.assertEqual(self.again, 1)

    def test_a_review_github_holds_counts_once_the_tick_has_lost_its_own_note(self):
        self.assertEqual(self.forgotten, 1)
        self.assertEqual(self.noted["reviewed"][self.url]["sha"], self.first)

    def test_a_push_is_a_new_head_and_is_reviewed_anew(self):
        self.assertEqual([review[:2] for review in self.reviews()],
                         [("acme", self.first), ("acme", self.second)])
        self.assertEqual([state["head_sha"] for state in self.pushed], [self.first, self.second])
        self.assertIn(f"--match-head-commit {self.second}", self.inbox.wait_lines(2)[1])


if __name__ == "__main__":
    unittest.main()
