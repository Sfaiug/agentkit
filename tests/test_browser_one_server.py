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
            tempfile.TemporaryDirectory(prefix=".ak-test-browser-one-", dir=REPO)))
        self.stack.enter_context(patch.object(browser, "CLAUDE_CONFIG",
                                              self.home / ".claude.json"))
        self.stack.enter_context(patch.object(browser, "CODEX_CONFIG",
                                              self.home / ".codex" / "config.toml"))
        self.stack.enter_context(patch.object(browser, "BRIDGE",
                                              self.home / ".local/share/browser-bridge"))
        self.stack.enter_context(patch.object(browser, "UNIT_DIR", self.home / "units"))
        # A fixed account at home in the temporary HOME, so the ownership and sandbox
        # guards answer the same whoever runs this: nothing here depends on the caller.
        self.me = "test-owner"
        self.stack.enter_context(patch.object(
            browser.pwd, "getpwuid",
            return_value=SimpleNamespace(pw_name=self.me, pw_dir=str(self.home))))
        self.stack.enter_context(patch.object(browser.Path, "home", return_value=self.home))
        self.commands, self.systemd = [], []
        self.active, self.enabled = False, False
        self.cat_overrides, self.loaded = {}, set()
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
        if args[0] == "is-enabled":
            return (0, "enabled\n") if self.enabled else (1, "disabled\n")
        if args[0] == "cat":
            return (0, self.cat_overrides[args[-1]]) if args[-1] in self.cat_overrides \
                else (1, "")
        if args[0] == "show":
            return (0, "loaded\n") if args[-1] in self.loaded else (0, "not-found\n")
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
        self.assertEqual(servers["browser"]["url"], "http://localhost:8931/mcp")
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
        self.assertIn('"/fake/bin/node"', installed)
        self.assertNotIn("/usr/bin/node", installed)
        # Once it is up, the same call changes nothing: no npm, no install, no enable,
        # no restart.  Only the read-only checks run.
        self.active, self.enabled = True, True
        self.commands.clear()
        self.systemd.clear()
        self.assertEqual(browser.ensure_mcp_service(), "already active")
        self.assertEqual(self.commands, [])
        verbs = [args[0] for args, _ in self.systemd]
        for verb in ("start", "restart", "enable", "daemon-reload"):
            self.assertNotIn(verb, verbs)

    def test_foreign_stack_is_left_untouched(self):
        units = self.home / "units"
        units.mkdir(exist_ok=True)
        (units / browser.UNITS[0]).write_text("[Service]\nUser=foreign-owner\n")
        self.assertIn("another account", browser.ensure_mcp_service())
        self.assertEqual(self.commands, [])
        verbs = [args[0] for args, _ in self.systemd]
        self.assertNotIn("enable", verbs)
        self.assertFalse((units / browser.MCP_UNIT).exists())
        self.assertFalse(browser.mcp_dir().exists())
        (units / browser.UNITS[0]).write_text(
            f"[Service]\nUser={self.me}\n# Browser bridge host: another-host\n")
        self.commands.clear()
        self.systemd.clear()
        self.assertIn("another host", browser.ensure_mcp_service())
        self.assertEqual(self.commands, [])
        # A drop-in override of User wins over the base file, as in the installer,
        # spaces around `=` included: both are valid systemd syntax.
        self.cat_overrides[browser.UNITS[0]] = (
            f"# {units / browser.UNITS[0]}\n[Service]\nUser={self.me}\n"
            "# /etc/systemd/system/owner.conf\n[Service]\nUser = foreign-owner\n")
        self.commands.clear()
        self.systemd.clear()
        self.assertIn("another account", browser.ensure_mcp_service())
        self.assertEqual(self.commands, [])

    def test_uninspectable_unit_refuses_loudly(self):
        self.loaded.add(browser.UNITS[0])
        with self.assertRaisesRegex(browser.config.Error, "cannot inspect"):
            browser.ensure_mcp_service()
        self.assertEqual(self.commands, [])
        self.assertFalse(browser.mcp_dir().exists())

    def test_install_refuses_before_any_mutation(self):
        units = self.home / "units"
        units.mkdir(exist_ok=True)
        (units / browser.UNITS[0]).write_text("[Service]\nUser=foreign-owner\n")
        with patch.object(browser, "missing_packages",
                          side_effect=AssertionError("packages must not be read")), \
                patch.object(browser, "unit_states",
                             side_effect=AssertionError("units must not be read")):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(browser.install([]), 0)
            self.assertIn("another account", output.getvalue())
        self.assertEqual(self.commands, [])

    def test_sandbox_home_installs_nothing(self):
        with patch.object(browser.Path, "home", return_value=self.home / "elsewhere"):
            self.assertIn("sandbox HOME", browser.ensure_mcp_service())
        self.assertEqual(self.commands, [])
        self.assertEqual(self.systemd, [])
        self.assertFalse(browser.mcp_dir().exists())

    def test_missing_node_fails_before_mutations(self):
        with patch.object(browser.shutil, "which",
                          side_effect=lambda name: None if name == "node"
                          else f"/fake/bin/{name}"):
            with self.assertRaisesRegex(browser.config.Error, "node is not installed"):
                browser.render_mcp_unit()
        self.assertEqual(self.commands, [])

    def test_status_reports_the_shared_server(self):
        states = {unit: "active (running)" for unit in browser.UNITS}
        with patch.object(browser, "unit_states", return_value=states), \
                patch.object(browser, "mcp_active", return_value=True), \
                patch.object(browser, "cdp", return_value={"Browser": "Test"}), \
                patch.object(browser, "tabs", return_value=[]), \
                patch.object(browser, "desktop_tools", return_value=("x", "y")), \
                patch.object(browser, "novnc_url", return_value="http://x/"), \
                patch.object(browser, "tab_records_path",
                             return_value=self.home / "no-tabs.json"):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(browser.status([]), 0)
            self.assertIn(f"{browser.MCP_URL} active", output.getvalue())
            with patch.object(browser, "mcp_active", return_value=False):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(browser.status([]), 1)
                self.assertIn("not active", output.getvalue())
        with patch.object(browser, "unit_states", return_value=None), \
                patch.object(browser, "cdp", side_effect=OSError("away")), \
                patch.object(browser, "desktop_tools", return_value=(None, None)), \
                patch.object(browser, "novnc_url", return_value=None):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(browser.status([]), 0)
            self.assertIn("mcp", output.getvalue())

    def test_no_latest_fetch_remains(self):
        sources = [REPO / "agentkit" / "browser.py", REPO / "browser" / "bootstrap.py",
                   REPO / "install.sh",
                   REPO / "browser" / "systemd" / "browser-bridge-mcp.service"]
        for path in sources:
            self.assertNotIn(LATEST, path.read_text(encoding="utf-8"), str(path))
        self.assertNotIn("npx", browser.codex_block())
        command, args = browser.servers()["browser"]
        self.assertNotIn("npx", command + "".join(args))
        template = (REPO / "browser" / "systemd" / browser.MCP_UNIT).read_text()
        self.assertIn("@NODE@", template)
        self.assertNotIn("/usr/bin/node", template)


if __name__ == "__main__":
    unittest.main()
