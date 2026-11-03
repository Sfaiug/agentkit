"""Incoming PR discovery asks GitHub once, across all local checkouts.

AK_BIN runs `watch` in a throwaway HOME against fakegh. Unrelated local passes are stilled
by the tick fixture; review subprocesses are recorded and answered without starting a run.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import AK, Home, REPO
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

QUIET = """
import json, pathlib, subprocess, sys
if sys.argv[0] == {ak!r}:
    sys.path[:0] = [{repo!r}, {tests!r}]
    from fixtures.tick import only_passes
    held = only_passes(pathlib.Path.home())
    held.__enter__()
    actual = subprocess.run
    def run(argv, **kwargs):
        if list(argv[2:4]) == ["run", "--review-pr"]:
            with pathlib.Path({launches!r}).open("a") as out:
                out.write(json.dumps(argv[2:]) + "\\n")
            return subprocess.CompletedProcess(argv, 0, {result!r} + "\\n", "")
        return actual(argv, **kwargs)
    subprocess.run = run
"""


class IncomingSearch(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        self.gh = GitHub(home)
        self.rigs = {name: Rig(home, name) for name in ("api", "web", "docs")}
        self.launches = home.path / "launches.jsonl"
        home.write("fakes/sitecustomize.py", QUIET.format(
            ak=AK, repo=str(Path(AK).resolve().parents[1]), tests=str(REPO / "tests"),
            launches=str(self.launches), result=str(home.path / "runs/review/result.md")))
        home.env["PYTHONPATH"] = str(home.path / "fakes")
        home.fake("ps", "#!/bin/sh\nexit 0\n")
        home.fake("tmux", "#!/bin/sh\nexit 1\n")

    def open_pr(self, name="web", *, author="someone-else", draft=False):
        rig = self.rigs[name]
        rig.branch("fix-api", {"fix.txt": "fixed\n"})
        url = self.gh.open_pr(rig, "fix-api", author=author)
        self.gh.edit(1, rig.slug, isDraft=draft)
        return url

    def tick(self):
        done = self.home.ak("watch")
        self.assertEqual((done.code, done.err), (0, ""), done.out)
        launched = ([json.loads(line) for line in self.launches.read_text().splitlines()]
                    if self.launches.exists() else [])
        # Identity and the separate outgoing-PR pass are outside incoming discovery.
        calls = [call for call in self.home.calls("gh") if call != ["api", "user"]
                 and not any("author:@me" in word for word in call)]
        return launched, calls

    def test_no_incoming_pr_makes_one_github_call(self):
        launched, calls = self.tick()
        self.assertEqual(launched, [])
        self.assertEqual(len(calls), 1, calls)
        self.assertIn("search/issues", calls[0])
        self.assertIn("--paginate", calls[0])

    def test_another_authors_pr_launches_its_review_from_local_origin_urls(self):
        url = self.open_pr()
        for name, remote in (("api", "https://github.com/acme/api.git"),
                             ("web", "git@github.com:Acme/Web.git"),
                             ("docs", "ssh://git@github.com/acme/docs.git")):
            self.rigs[name].git("remote", "set-url", "origin", remote)
        launched, calls = self.tick()
        self.assertEqual(launched, [["run", "--review-pr", url, "--bg"]])
        self.assertFalse(any(call[:2] == ["repo", "view"] for call in calls))
        noted = json.loads((self.home.path / ".agentkit/state/watch.json").read_text())
        self.assertEqual(noted["reviewed"][url]["sha"], self.rigs["web"].head("fix-api"))

    def test_drafts_and_the_owners_prs_launch_nothing(self):
        self.open_pr("api", draft=True)
        self.open_pr("docs", author="acme")
        launched, calls = self.tick()
        self.assertEqual((launched, len(calls)), ([], 1), calls)

    def test_an_origin_on_another_host_does_not_make_a_github_checkout(self):
        self.open_pr()
        for count, origin in enumerate(("https://gitlab.com/acme/web.git",
                                        "git@gitlab.com:acme/web.git",
                                        "ssh://git@gitlab.com/acme/web.git"), 1):
            with self.subTest(origin=origin):
                self.rigs["web"].git("remote", "set-url", "origin", origin)
                launched, calls = self.tick()
                self.assertEqual(launched, [])
                self.assertEqual(len(calls), count, calls)

    def test_a_pr_on_a_later_search_page_is_reviewed_but_an_uncloned_repo_is_not_read(self):
        url = self.open_pr()
        found = {"number": 1, "pull_request": {"html_url": url}}
        other = {"number": 2, "pull_request": {
            "html_url": "https://github.com/acme/uncloned/pull/2"}}
        self.gh.reply("api --paginate search/issues -X GET", out=
                      json.dumps({"items": [other]}) + "\n" + json.dumps({"items": [found]}))
        launched, calls = self.tick()
        self.assertEqual(launched, [["run", "--review-pr", url, "--bg"]])
        self.assertFalse(any("uncloned" in word for call in calls for word in call))

    def test_unavailable_pr_details_do_not_launch_a_review(self):
        self.open_pr()
        self.gh.reply("api repos/acme/web/pulls/1", code=1, err="HTTP 503")
        self.assertEqual(self.tick()[0], [])


if __name__ == "__main__":
    unittest.main()
