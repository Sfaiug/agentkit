"""A character terminal fonts do not carry is counted on any line of ak's code, Python's or Go's,
and not where a character is not a screen's (docs/cli-design.md, Characters)."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_boundaries as boundaries

RULE = next(rule for rule in boundaries.RULES
            if rule["name"] == "a character terminal fonts do not carry")
BORROWED = ["▰▰▱▱▱", "⚒ build", "✗ refused", "⠋ waiting", "✅ done"]
CARRIED = ["━━━╸───", "● working", "✓ done", "↑↓←→ move   ⏎ open", "× … · −"]


class ScreenCharacters(unittest.TestCase):
    def test_only_a_borrowed_character_outside_its_home_counts(self):
        # a screen read and a harness manifest are its home; the adapter script beside it is not
        files = {"agentkit/menu.py": BORROWED + CARRIED, "go/internal/menu/frame.go": BORROWED,
                 "agentkit/watch.py": ["▰▰▱▱▱"], "adapters/acme.toml": ["▰▰▱▱▱"],
                 "adapters/acme.sh": ["▰▰▱▱▱"]}
        with tempfile.TemporaryDirectory(prefix="ak-characters-") as directory:
            repo = Path(directory)
            for name, lines in files.items():
                (repo / name).parent.mkdir(parents=True, exist_ok=True)
                (repo / name).write_text("\n".join(lines) + "\n")
            subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
            with patch.object(boundaries, "REPO", repo):
                found = boundaries.outside(RULE)
        self.assertEqual(found, ["adapters/acme.sh:1:▰▰▱▱▱"] + [
            f"{name}:{number}:{line}" for name in ("agentkit/menu.py", "go/internal/menu/frame.go")
            for number, line in enumerate(BORROWED, 1)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
