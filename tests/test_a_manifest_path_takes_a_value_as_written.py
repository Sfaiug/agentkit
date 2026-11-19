"""A manifest path takes a variable's value as written, its dollars included, whether the path
names it `$NAME` or `${NAME:-default}`: only what the manifest writes is a template."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import config


class ValueAsWritten(unittest.TestCase):
    def test_a_dollar_in_a_value(self):
        env = {"HOME": "/home/acme", "ACME_STATE": "/data/$project"}
        names = ["$ACME_STATE/file", "${ACME_STATE:-fallback}/file", "${UNSET:-$HOME}/file"]
        self.assertEqual(list(config.manifest_paths(names, env)),
                         [Path("/data/$project/file")] * 2 + [Path("/home/acme/file")])


if __name__ == "__main__":
    unittest.main()
