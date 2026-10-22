"""`ak browser` refuses a word or an argument it does not take, and `mcp-register` points the
harnesses at the shared browser and the desktop by editing only their own configs, once.

A model reaches for `ak browser` with the wrong word or a stray argument; that must stop before
anything starts, a service, an install or a login.  Registration writes into files Claude Code,
Codex and their owner also write, so it adds its two servers and keeps every other key, says
which harnesses it could not register, and on a second run changes nothing.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py.
"""

import json
import shlex
import sys
from pathlib import Path
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REFUSE, REFUSED, Home

USAGE = "usage: ak browser <status|login|mcp-register|install>"
MCP_URL = "http://localhost:8931/mcp"
BEGIN = "# --- agentkit browser bridge: managed by `ak browser mcp-register` ---"
END = "# --- end agentkit browser bridge ---"
UNREGISTERED = "not registered, their plugins write no MCP entry: "
HAND_WRITTEN = '# chosen by hand\nmodel = "beta"\n\n[mcp_servers.acme]\ncommand = "acme-mcp"\n'
ACME = {"type": "stdio", "command": "acme-mcp"}


class Refusals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.fake("sudo", REFUSE.format(python=shlex.quote(sys.executable), name="sudo",
                                            log=shlex.quote(str(cls.home.log("sudo")))))

    def assertNothingStarted(self):
        for tool in (*REFUSED, "sudo"):
            self.assertEqual(self.home.calls(tool), [], tool)

    def test_browser_alone_prints_its_help_and_exits_2(self):
        done = self.home.ak("browser")
        self.assertEqual(done.code, 2, done.err)
        self.assertIn(USAGE, done.out.splitlines())
        self.assertEqual(done.out, self.home.ak("browser", "-h").out)
        self.assertNothingStarted()

    def test_an_unknown_sub_verb_names_the_four_it_takes(self):
        done = self.home.ak("browser", "bogus")
        self.assertEqual(done.code, 2, done.out)
        self.assertEqual(done.err, "ak browser: unknown command 'bogus'; expected one of "
                                   "status, login, mcp-register, install\n")
        self.assertNothingStarted()

    def test_each_sub_verb_refuses_an_argument_before_doing_anything(self):
        for sub in ("status", "login", "mcp-register", "install"):
            for extra in (["extra"], ["acme", "beta"]):
                with self.subTest(sub=sub, extra=extra):
                    done = self.home.ak("browser", sub, *extra)
                    self.assertEqual(done.code, 2, done.out)
                    self.assertEqual(done.err, f"ak browser: ak browser {sub} takes no "
                                               f"arguments; got {' '.join(extra)}\n")
        self.assertFalse((self.home.path / ".claude.json").exists())
        self.assertFalse((self.home.path / ".codex").exists())
        self.assertNothingStarted()


class Register(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.claude = home.write(".claude.json", {"other": 1, "mcpServers": {"acme": ACME}})
        cls.codex = home.write(".codex/config.toml", HAND_WRITTEN)
        cls.first = home.ak("browser", "mcp-register")
        cls.after_first = cls.claude.read_bytes(), cls.codex.read_bytes()
        cls.second = home.ak("browser", "mcp-register")

    def test_claude_gets_both_servers_beside_the_keys_it_had(self):
        self.assertEqual(self.first.code, 0, self.first.err)
        data = json.loads(self.after_first[0])
        self.assertEqual(data["other"], 1)
        servers = data["mcpServers"]
        self.assertEqual(servers["acme"], ACME)
        self.assertEqual(servers["browser"], {"type": "http", "url": MCP_URL})
        desktop = servers["desktop"]
        self.assertEqual(desktop["type"], "stdio")
        self.assertTrue(desktop["args"][0].endswith("tools/desktop-mcp.py"), desktop)
        xauthority = str(self.home.path / ".local/share/browser-bridge/Xauthority")
        self.assertEqual(desktop["env"], {"DISPLAY": ":99", "XAUTHORITY": xauthority})

    def test_codex_gets_one_marked_block_after_what_was_written_by_hand(self):
        text = self.after_first[1].decode()
        self.assertTrue(text.startswith(HAND_WRITTEN), text)
        lines = text.splitlines()
        self.assertEqual(lines.count(BEGIN), 1, text)
        self.assertEqual(lines.count(END), 1, text)
        block = lines[lines.index(BEGIN):lines.index(END) + 1]
        self.assertIn("[mcp_servers.browser]", block)
        self.assertIn("[mcp_servers.desktop]", block)
        servers = tomllib.loads(text)["mcp_servers"]
        self.assertEqual(servers["acme"], {"command": "acme-mcp"})
        self.assertEqual(servers["browser"], {"url": MCP_URL})
        self.assertTrue(servers["desktop"]["args"][0].endswith("tools/desktop-mcp.py"))
        self.assertEqual(servers["desktop"]["env"]["DISPLAY"], ":99")

    def test_it_names_the_harnesses_whose_plugins_write_no_entry(self):
        named = [line for line in self.first.out.splitlines() if line.startswith(UNREGISTERED)]
        self.assertEqual(len(named), 1, self.first.out)
        harnesses = named[0][len(UNREGISTERED):].split(";")[0].split(", ")
        self.assertEqual(sorted(harnesses), ["antigravity", "grokbuild", "muse", "opencode"])

    def test_a_second_run_says_already_registered_and_changes_nothing(self):
        self.assertEqual(self.second.code, 0, self.second.err)
        said = [line for line in self.second.out.splitlines() if "already registered" in line]
        self.assertEqual(len(said), 2, self.second.out)
        self.assertEqual((self.claude.read_bytes(), self.codex.read_bytes()), self.after_first)


if __name__ == "__main__":
    unittest.main()
