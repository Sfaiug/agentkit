"""A clone is named after the repository git really borrows from, however its alternate is written:
a link on the way can lead to an unrelated repository's objects, and a name shared with it would mix
their machine copies and recorded test times.  Temporary HOME, real git.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
HOME = tempfile.TemporaryDirectory(prefix="ak-alternate-")
ROOT = Path(HOME.name).resolve()
os.environ.update(HOME=str(ROOT), GIT_CONFIG_NOSYSTEM="1")
from agentkit import gitcall  # noqa: E402


def git(*args):
    return subprocess.run(["git", *map(str, args)], check=True, capture_output=True, text=True).stdout.strip()


class AnAlternate(unittest.TestCase):
    def test_names_what_git_reads_through_a_link_on_the_way(self):
        for name in ("acme", "gadget"):
            git("init", "-q", ROOT / name)
            (ROOT / name / "name.txt").write_text(name)
            git("-C", ROOT / name, "add", ".")
            git("-C", ROOT / name, "-c", "user.name=Acme", "-c", "user.email=acme@example.invalid", "commit", "-qm", name)
        (ROOT / "acme" / "linked").symlink_to(ROOT / "gadget" / ".git", target_is_directory=True)
        clone = ROOT / "clone"
        git("clone", "-q", "--shared", ROOT / "gadget", clone)
        for alternate in (f"{ROOT}/acme/linked/../.git/objects", "../../../acme/linked/../.git/objects"):
            with self.subTest(alternate):
                (clone / ".git/objects/info/alternates").write_text(alternate + "\n")
                self.assertEqual(git("-C", clone, "cat-file", "-p", "HEAD:name.txt"), "gadget")
                self.assertEqual(gitcall.repository_id(clone), gitcall.repository_id(ROOT / "gadget"))
                self.assertNotEqual(gitcall.repository_id(clone), gitcall.repository_id(ROOT / "acme"))


if __name__ == "__main__":
    unittest.main()
