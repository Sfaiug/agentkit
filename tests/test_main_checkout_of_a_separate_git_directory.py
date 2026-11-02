"""A checkout whose git directory is elsewhere is still the checkout: a follow-up filed under
`main_checkout` has to find it again, and a bare repository, which has no checkout, is its own.
Temporary HOME, real git.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
HOME = tempfile.TemporaryDirectory(prefix="ak-main-checkout-")
ROOT = Path(HOME.name).resolve()
os.environ.update(HOME=str(ROOT), GIT_CONFIG_NOSYSTEM="1")
from agentkit import gitcall, plan  # noqa: E402


def git(*args):
    subprocess.run(["git", *map(str, args)], check=True, capture_output=True)


class MainCheckout(unittest.TestCase):
    def test_a_separate_git_directory_inside_the_checkout_leaves_it_the_checkout(self):
        repo = ROOT / "acme"
        git("init", "-q", "--separate-git-dir", repo / "metadata", repo)
        git("-C", repo, "-c", "user.name=Acme", "-c", "user.email=acme@example.invalid",
            "commit", "--allow-empty", "-qm", "initial")
        self.assertEqual(gitcall.main_checkout(repo), repo)
        self.assertEqual(plan.place("acme", plan.named(gitcall.main_checkout(repo))), repo)

    def test_a_bare_repository_is_its_own_unless_it_is_the_git_directory_of_its_folder(self):
        for bare, own in ((ROOT / "acme.git", ROOT / "acme.git"), (ROOT / "gadget" / ".git", ROOT / "gadget")):
            git("init", "-q", "--bare", bare)
            self.assertEqual(gitcall.main_checkout(bare), own)


if __name__ == "__main__":
    unittest.main()
