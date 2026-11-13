"""go/ holds Go's program and what ships with it, and nothing else.

On 12 Nov 2026 two probes written during reviews had been merged at its top: a directory holding a
Go test of its own, which every `go test ./...` then ran, and a script.  A name new at the top of
go/ is a decision, made by adding it to OWN.
"""
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OWN = {".gitignore", "adapters", "cmd", "config.default.toml", "go.mod", "go.sum", "hooks",
       "install.sh", "internal", "keys.txt", "leans", "toolchain.sha256", "tools", "vendor"}


class GoHoldsOnlyItsOwn(unittest.TestCase):
    def test_every_tracked_name_at_the_top_of_go_is_one_of_its_own(self):
        tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "go"],
                                 capture_output=True, text=True, check=True).stdout.split("\0")
        found = {name.split("/")[1] for name in tracked if name}
        self.assertEqual(found - OWN, set(), "not Go's own: a review's probe left behind?")
        # go/leans/ empties as claims stop leaning on Python, and git keeps no empty folder
        self.assertEqual(OWN - found - {"leans"}, set(), "named in OWN and gone from go/")


if __name__ == "__main__":
    unittest.main()
