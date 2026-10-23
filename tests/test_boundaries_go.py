"""Go has named knowledge owners; fixtures are exempt, other Go product code is not."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_boundaries as boundaries


class GoBoundaries(unittest.TestCase):
    def test_owners_and_fixtures_do_not_hide_copies_in_product_code(self):
        with tempfile.TemporaryDirectory(prefix="ak-boundaries-") as directory:
            repo = Path(directory)
            files = {
                "go/internal/config/default.toml": 'harness = "claude"\n',
                "go/internal/config/session.go": 'record["renamed"]\n',
                "go/internal/job/receipt.go": 'return "job.json"\n',
            }
            copies = 'var harness = "claude"\nvar pointer = "renamed"\nvar receipt = "job.json"\n'
            files["go/internal/cli/refusals_test.go"] = copies
            files["go/internal/config/duplicate.go"] = copies
            for name, text in files.items():
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
            with patch.object(boundaries, "REPO", repo):
                for line, name in enumerate(("harness and provider names", "rename chain walks",
                                             "job receipt"), 1):
                    with self.subTest(rule=name):
                        rule = next(rule for rule in boundaries.RULES if rule["name"] == name)
                        self.assertEqual(boundaries.outside(rule), [
                            f"go/internal/config/duplicate.go:{line}:{copies.splitlines()[line - 1]}"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
