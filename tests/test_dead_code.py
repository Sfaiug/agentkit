"""Every top-level definition has another whole-word mention in the tracked product.

Strings count too: entry tables, manifests and plugin hooks can name a caller.
Tests and docs cannot keep a definition alive. Offline, one scan per product file.
"""

import ast
from collections import Counter
from pathlib import Path
import re
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[1]
SCOPE = ("agentkit/", "bin/", "hooks/", "tools/", "adapters/", "install.sh", "*.toml",
         ":!tests/", ":!docs/", ":!*.md")


class DeadCode(unittest.TestCase):
    def test_every_definition_has_another_mention(self):
        paths = subprocess.check_output(
            ["git", "-C", str(REPO), "ls-files", "-z", "--", *SCOPE], text=True)
        mentions = Counter()
        definitions = []
        for name in filter(None, paths.split("\0")):
            source = (REPO / name).read_text(encoding="utf-8", errors="replace")
            mentions.update(re.findall(r"\b\w+\b", source))
            if name.startswith("agentkit/") and name.endswith(".py"):
                for node in ast.parse(source, filename=name).body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        definitions.append((name, node.lineno, node.name))
        dead = [f"{path}:{line} {name}" for path, line, name in definitions
                if mentions[name] == 1]
        if dead:
            self.fail("definitions named only by themselves:\n" + "\n".join(dead))


if __name__ == "__main__":
    unittest.main(verbosity=2)
