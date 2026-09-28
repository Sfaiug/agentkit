"""One browser tool process serves every seat.

Claude Code and Codex are registered to the shared Playwright MCP server by URL;
a harness without URL support keeps a per-session stdio command onto the same
pinned install.  The service is set up once by `ak browser install`, never per
session, and nothing fetches `@latest` through `npx` any more.

Nothing here starts a real unit or process or touches the real ~/.claude.json:
systemctl and subprocess are injected fakes, HOME is a temporary directory.
"""
import io
import json
import sys
import tomllib
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agentkit import browser


LATEST = "@playwright/mcp@latest"


class OneServer(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.home = Path(self.stack.enter_context(
            tempfile.TemporaryDirectory(prefix=".browser-one-", dir=REPO)))
        self.stack.enter_context(patch.object(browser, "CLAUDE_CONFIG",
                                              self.home / ".claude.json"))
        self.stack.enter_context(patch.object(browser, "CODEX_CONFIG",
                                              self.home / ".codex" / "config.toml"))
        self.stack.enter_context(patch.object(browser, "BRIDGE",
                                              self.home / ".local/share/browser-bridge"))
        self.stack.enter_context(patch.object(browser, "UNIT_DIR", self.home / "units"))
        self.commands, self.systemd = [], []
        self.active = False
        self.stack.enter_context(patch.object(browser.subprocess, "run",
                                              side_effect=self.fake_run))
        self.stack.enter_context(patch.object(browser, "systemctl",
                                              side_effect=self.fake_systemctl))
        self.stack.enter_context(patch.object(browser.shutil, "which",
                                              side_effect=self.fake_which))

    def fake_which(self, name):
        if name in ("npm", "systemctl", "node"):
            return f"/fake/bin/{name}"
        return None

    def fake_run(self, cmd, **kwargs):
        self.commands.append(list(cmd))
        if cmd[0] == "npm":
            package = browser.mcp_dir() / "node_modules" / "@playwright" / "mcp"
            package.mkdir(parents=True, exist_ok=True)
            (package / "package.json").write_text(
                json.dumps({"version": browser.PLAYWRIGHT_MCP_VERSION}))
        elif cmd[:3] == ["sudo", "-n", "install"]:
            staged, target = Path(cmd[-2]), Path(cmd[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(staged.read_bytes())
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_systemctl(self, args, sudo=False, cap=120):
        self.systemd.append((list(args), sudo))
        if args[0] == "is-active":
            return (0, "active\n") if self.active else (3, "inactive\n")
        return 0, ""

    def test_url_harnesses_register_the_shared_server(self):
        self.assertEqual(browser.URL_CAPABLE, frozenset({"claude", "codex"}))
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(browser.mcp_register([]), 0)
        claude_text = (self.home / ".claude.json").read_text(encoding="utf-8")
        codex_text = (self.home / ".codex" / "config.toml").read_text(encoding="utf-8")
        servers = json.loads(claude_text)["mcpServers"]
        self.assertEqual(servers["browser"], {"type": "http", "url": browser.MCP_URL})
        self.assertEqual(servers["browser"]["url"], "http://127.0.0.1:8931/mcp")
        self.assertTrue(servers["desktop"]["args"][0].endswith("desktop-mcp.py"))
        codex = tomllib.loads(codex_text)
        self.assertEqual(codex["mcp_servers"]["browser"], {"url": browser.MCP_URL})
        self.assertIn("command", codex["mcp_servers"]["desktop"])
        for text in (claude_text, codex_text):
            self.assertNotIn("npx", text)
            self.assertNotIn(LATEST, text)
        # A second registration changes nothing: the shared server needs no per-seat setup.
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(browser.mcp_register([]), 0)
        self.assertIn("already registered", output.getvalue())

    def test_harness_without_url_keeps_a_pinned_command(self):
        command, args = browser.servers()["browser"]
        self.assertEqual(command, "node")
        self.assertEqual(args[-2:], ["--cdp-endpoint", browser.CDP])
        self.assertNotIn("--isolated", args)
        self.assertEqual(Path(args[0]), browser.mcp_cli())
        self.assertNotIn("npx", command + "".join(args))
        self.assertNotIn(LATEST, "".join(args))
        self.assertNotEqual(browser.PLAYWRIGHT_MCP_VERSION, "latest")
        self.assertNotIn("latest", f"@playwright/mcp@{browser.PLAYWRIGHT_MCP_VERSION}")

    def test_registering_sets_up_no_service(self):
        with patch.object(browser, "systemctl",
                          side_effect=AssertionError("mcp-register must not touch units")), \
                patch.object(browser.subprocess, "run",
                             side_effect=AssertionError("mcp-register must not run anything")):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(browser.mcp_register([]), 0)
        self.assertTrue((self.home / ".claude.json").exists())

    def test_setup_runs_once_then_is_a_noop(self):
        self.assertEqual(browser.ensure_mcp_service(), "installed and started")
        npm = [cmd for cmd in self.commands if cmd[0] == "npm"]
        self.assertEqual(len(npm), 1)
        self.assertIn(f"@playwright/mcp@{browser.PLAYWRIGHT_MCP_VERSION}", npm[0])
        self.assertIn("--save-exact", npm[0])
        verbs = [args[0] for args, _ in self.systemd]
        self.assertIn("daemon-reload", verbs)
        self.assertIn("enable", verbs)
        self.assertIn("start", verbs)
        self.assertNotIn("restart", verbs)
        installed = (self.home / "units" / browser.MCP_UNIT).read_text(encoding="utf-8")
        self.assertIn("--shared-browser-context", installed)
        self.assertIn("--cdp-endpoint http://127.0.0.1:9222", installed)
        self.assertNotIn("--isolated", installed)
        self.assertNotRegex(installed, r"@[A-Z0-9_]+@")
        # Once it is up, the same call changes nothing: no npm, no install, no restart.
        self.active = True
        self.commands.clear()
        self.systemd.clear()
        self.assertEqual(browser.ensure_mcp_service(), "already active")
        self.assertEqual(self.commands, [])
        verbs = [args[0] for args, _ in self.systemd]
        self.assertNotIn("start", verbs)
        self.assertNotIn("restart", verbs)
        self.assertNotIn("daemon-reload", verbs)

    def test_no_latest_fetch_remains(self):
        sources = [REPO / "agentkit" / "browser.py", REPO / "browser" / "bootstrap.py",
                   REPO / "install.sh",
                   REPO / "browser" / "systemd" / "browser-bridge-mcp.service"]
        for path in sources:
            self.assertNotIn(LATEST, path.read_text(encoding="utf-8"), str(path))
        self.assertNotIn("npx", browser.codex_block())
        command, args = browser.servers()["browser"]
        self.assertNotIn("npx", command + "".join(args))


if __name__ == "__main__":
    unittest.main()
