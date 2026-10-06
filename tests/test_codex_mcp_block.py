"""Registering MCP servers with Codex changes only agentkit's own block of its config.

`register_mcp` keeps the servers in one marked block of ~/.codex/config.toml.  A marker counts
only as a line of its own, and a write that would change anything else in the file is
refused before it lands.  HOME is a temporary directory; no real config is read or written.
"""
import sys
import tempfile
import tomllib
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agentkit import config
from agentkit.harness import codex

SERVERS = {"browser": {"url": "http://localhost:8931/mcp"},
           "desktop": {"command": "python3", "args": ["desktop-mcp.py"], "env": {"DISPLAY": ":1"}}}
OLD = {"browser": {"url": "http://localhost:9999/mcp"}, **{k: v for k, v in SERVERS.items()
                                                          if k != "browser"}}


class CodexBlock(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        home = Path(stack.enter_context(
            tempfile.TemporaryDirectory(prefix=".ak-test-codex-block-", dir=REPO)))
        stack.enter_context(patch.object(codex.Path, "home", return_value=home))
        self.path = home / ".codex" / "config.toml"
        self.path.parent.mkdir()

    def register(self, text):
        self.path.write_text(text, encoding="utf-8")
        return codex.register_mcp(SERVERS)

    def refused(self, text):
        with self.assertRaises(config.Error):
            self.register(text)
        self.assertEqual(self.path.read_text(encoding="utf-8"), text)

    def test_a_comment_quoting_a_marker_is_no_block(self):
        note = f'# the line "{codex.BEGIN}" starts what ak keeps\n'
        self.register(note + 'model = "example"\n\n' + codex.mcp_block(OLD))
        text = self.path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(note + 'model = "example"\n'))
        data = tomllib.loads(text)
        self.assertEqual(data["model"], "example")
        self.assertEqual(data["mcp_servers"]["browser"], SERVERS["browser"])
        self.assertEqual(text.count(codex.mcp_block(SERVERS)), 1)

    def test_what_is_around_the_block_stays_as_it_was(self):
        head = 'model = "example"\n\n[mcp_servers.other]\nurl = "http://localhost:1/mcp"\n\n'
        tail = '[projects."/home/someone/code"]\ntrust_level = "trusted"\n'
        self.register(head + codex.mcp_block(OLD) + "\n" + tail)
        self.assertEqual(self.path.read_text(encoding="utf-8"),
                         head + codex.mcp_block(SERVERS) + "\n" + tail)
        self.assertEqual(self.register(self.path.read_text(encoding="utf-8")),
                         f"already registered in {self.path}")

    def test_a_server_the_old_block_held_goes_with_it(self):
        self.register(codex.mcp_block({**OLD, "playwright": {"url": "http://localhost:2/mcp"}}))
        self.assertEqual(set(tomllib.loads(self.path.read_text(encoding="utf-8"))["mcp_servers"]),
                         set(SERVERS))

    def test_a_setting_between_the_markers_is_refused(self):
        block = codex.mcp_block(OLD)
        self.refused(block.replace(codex.BEGIN + "\n", codex.BEGIN + '\nmodel = "example"\n'))

    def test_a_marker_twice_or_alone_is_refused(self):
        block = codex.mcp_block(OLD)
        self.refused(codex.BEGIN + "\n" + block)
        self.refused(block + codex.END + "\n")
        self.refused('model = "example"\n' + codex.BEGIN + "\n")
        self.refused(codex.END + "\n" + 'model = "example"\n' + codex.BEGIN + "\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
