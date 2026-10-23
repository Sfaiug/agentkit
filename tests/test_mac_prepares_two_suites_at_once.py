"""Two suites prepare on the Mac at once, of two repositories or of one, and both end ready:
neither's build is stopped by the other's, the history copy stays whole with both suites' refs,
and no image either prepared goes. Offline: tests/test_suite_helper.py's fake Mac.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import helper
from test_suite_helper import MAC_TOOLS


class TwoSuitesPrepare(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-two-prepares-")
        self.addCleanup(tmp.cleanup)
        self.fake = Path(tmp.name)
        for name, body in MAC_TOOLS.items():
            (self.fake / name).write_text(f"#!/bin/bash\n{body}\n")
            (self.fake / name).chmod(0o755)
        self.mirrors = self.fake / ".agentkit-helper" / "mirrors"
        self.repo = self.fake / "repo"
        self.git("init", "-q", "-b", "main", str(self.repo))
        for context in (patch.object(helper, "SSH", (str(self.fake / "ssh"),)), patch.dict(
                os.environ, {"PATH": f"{self.fake}:{os.environ['PATH']}", "HOME": str(self.fake),
                             "FAKE": str(self.fake), "FAKE_AC_CALLS": "99"})):
            context.start()
            self.addCleanup(context.stop)

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=acme", "-c", "user.email=a@acme.test",
                               *args], capture_output=True, text=True, check=True).stdout.strip()

    def commit(self):
        self.git("-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "change")
        self.git("-C", str(self.repo), "update-ref", "refs/remotes/origin/main", "HEAD")
        return self.git("-C", str(self.repo), "rev-parse", "HEAD")

    def prepares(self, *suites):
        """Each (key, image, repo) prepares at once, each sending the whole history at its own
        commit: their exits."""
        recipe = {"image/Containerfile": (0o644, (helper.TOOLS / "Containerfile").read_bytes())}
        parcels = []
        for _ in suites:
            self.commit()
            parcels.append(tempfile.TemporaryFile())
            helper._parcel(self.repo, "main", [], recipe, parcels[-1])
            parcels[-1].seek(0)
        running = [subprocess.Popen(helper._remote("acme-mac", "prepare", *suite), stdin=parcel,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                   for suite, parcel in zip(suites, parcels)]
        codes = [each.wait(60) for each in running]
        for parcel in parcels:
            parcel.close()
        return codes

    def test_two_repositories_both_build(self):
        images = ["ak-helper-acme:one", "ak-helper-other:one"]
        self.assertEqual(self.prepares(("first", images[0], "acme"),
                                       ("second", images[1], "other")), [0, 0])
        self.assertEqual([(self.fake / f"has-{image}").exists() for image in images], [True, True])

    def test_one_repository_with_different_recipes(self):
        images = ["ak-helper-acme:one", "ak-helper-acme:two"]
        self.assertEqual(self.prepares(("first", images[0], "acme"),
                                       ("second", images[1], "acme")), [0, 0])
        self.assertEqual([(self.fake / f"has-{image}").exists() for image in images], [True, True])
        mirror = str(self.mirrors / "acme")
        refs = self.git("-C", mirror, "for-each-ref", "--format=%(refname)", "refs/suites")
        self.assertEqual(sorted(ref.split("/")[2] for ref in refs.splitlines()),
                         ["first", "first", "second", "second"])
        self.git("-C", mirror, "fsck", "--strict")


if __name__ == "__main__":
    unittest.main()
