"""A Mac's ~/agentkit keeps updating when Finder has left `.DS_Store` files in it.

Offline: a checkout made here under this test's HOME, with the repository's own .gitignore.
"""

import shutil
import subprocess
import unittest

from fixtures.sandbox import REPO, Sandbox
from agentkit import update


class FinderFiles(Sandbox):
    def git(self, *args):
        subprocess.run(["git", "-C", str(self.checkout), *args], check=True,
                       capture_output=True, text=True)

    def setUp(self):
        super().setUp()
        self.checkout = update.agentkit_dir()
        (self.checkout / "agentkit").mkdir(parents=True)
        shutil.copy(REPO / ".gitignore", self.checkout / ".gitignore")
        (self.checkout / "agentkit" / "acme.py").write_text("acme = 1\n")
        self.git("init", "-q", "-b", "main")
        self.git("add", ".")
        self.git("-c", "user.name=acme", "-c", "user.email=acme@example.invalid",
                 "commit", "-qm", "acme")

    def test_finder_files_leave_the_checkout_free_to_update(self):
        for folder in (self.checkout, self.checkout / "agentkit"):
            (folder / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
        (self.checkout / "agentkit" / "._acme.py").write_bytes(b"\x00\x05\x16\x07")
        self.assertEqual(update.left_as_is(), "")

    def test_a_file_of_the_owners_still_holds_it(self):
        (self.checkout / "agentkit" / "notes.txt").write_text("acme notes\n")
        self.assertEqual(update.left_as_is(), "dirty")


if __name__ == "__main__":
    unittest.main(verbosity=2)
