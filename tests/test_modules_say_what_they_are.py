"""Every module and every adapter says what it is in its own opening lines, so the code is its own map.

A module under agentkit/ opens with a docstring; an adapter under adapters/ opens with a
comment, after its shebang.  A separate map of them would be a second copy that goes stale.
Offline: the files of this checkout.
"""

import ast
from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parents[1]


class ModulesSayWhatTheyAre(unittest.TestCase):
    def test_every_module_opens_with_a_docstring(self):
        bare = [path.name for path in sorted((REPO / "agentkit").glob("*.py"))
                if not (ast.get_docstring(ast.parse(path.read_text())) or "").strip()]
        self.assertEqual(bare, [], "these agentkit/ modules do not say what they are")

    def test_every_adapter_opens_with_a_comment(self):
        bare = []
        for path in sorted((REPO / "adapters").iterdir()):
            if path.suffix not in (".toml", ".sh"):
                continue
            lines = [line for line in path.read_text().splitlines() if not line.startswith("#!")]
            if not (lines and lines[0].startswith("# ") and lines[0][2:].strip()):
                bare.append(path.name)
        self.assertEqual(bare, [], "these adapters do not say what they are")


if __name__ == "__main__":
    unittest.main()
