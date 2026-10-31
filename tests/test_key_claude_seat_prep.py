"""A Claude seat opens on the prompt: its folder trusted and onboarding done before claude starts.

Claude Code asks a new login to pick a theme and finish onboarding, offers auto mode, and asks
"do you trust this folder?" with "No, exit" as its default: a seat that opened on any of them
would sit there or quit.  So the line `adapters/claude.sh interactive` prints for `ak orch`
answers them in `~/.claude.json`, in the seat's own folder, before it starts claude, keeping
everything the owner had there; a file it could not read back is refused before claude starts,
never replaced, since it holds the owner's login and projects.  A seat on a named login opens
with the usual login's MCP servers, the shared browser and desktop among them.

Black-box: the adapters beside the program `AK_BIN` names (or `AK_ROOT`'s) print the line, and
a shell runs it in the seat's folder with a fake `claude` that keeps what it found on starting;
this test fails against `/bin/false`.
"""

import json
import os
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, LOG, Home

ADAPTERS = Path(os.environ.get("AK_ROOT") or Path(AK).resolve().parents[1]) / "adapters"
UNREADABLE = ((".claude.json", "{bad"), (".claude.json", "[]"),
              (".claude/settings.json", "{bad"))


class ClaudeSeatPrep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.config, cls.saw = home.path / ".claude.json", home.root / "claude-saw.json"
        # Logs each start, and keeps the config as claude found it on starting.
        home.fake("claude", LOG.format(python=shlex.quote(sys.executable),
                                       log=shlex.quote(str(home.log("claude"))))
                  + 'cat "${CLAUDE_CONFIG_DIR:-$HOME}/.claude.json" >'
                  + f'{shlex.quote(str(cls.saw))}\n')
        cls.cwd = home.path / "code" / "acme"
        cls.cwd.mkdir(parents=True)
        cls.env = {"AGENTKIT_SESSION": "acme",
                   "AGENTKIT_RULEBOOK": str(home.write("rb.md", "rb\n"))}

    def setUp(self):
        self.reset()

    def reset(self):
        """No config, no settings, and nothing claude saw."""
        for path in (self.config, self.home.path / ".claude/settings.json", self.saw,
                     self.home.path / ".claude-harbor/.claude.json"):
            path.unlink(missing_ok=True)

    def line(self, **env):
        return self.home.run("bash", str(ADAPTERS / "claude.sh"), "interactive", "opus", "xhigh",
                             env={**self.env, **env}, cwd=self.cwd)

    def launch(self, line, **env):
        return self.home.run("sh", "-c", line, env={**self.env, **env}, cwd=self.cwd)

    def opened(self, **env):
        """The config claude found on starting, once the seat's line has run."""
        printed = self.line(**env)
        self.assertEqual(printed.code, 0, printed.err)
        starts = len(self.home.calls("claude"))
        done = self.launch(printed.out, **env)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(len(self.home.calls("claude")), starts + 1)
        return json.loads(self.saw.read_text())

    def assertRefused(self, done, path, held, starts):
        self.assertNotEqual(done.code, 0, done.out)
        self.assertIn(str(path), done.err)
        self.assertEqual(path.read_text(), held)
        self.assertEqual(len(self.home.calls("claude")), starts)

    def test_the_owners_config_is_kept_and_the_first_run_questions_answered(self):
        self.home.write(".claude.json", {
            "theme": "light", "numStartups": 7,
            "projects": {"/srv/beta": {"hasTrustDialogAccepted": False},
                         str(self.cwd): {"allowedTools": ["Bash"]}}})
        self.config.chmod(0o640)
        saw = self.opened()
        self.assertEqual(saw["theme"], "light")
        self.assertEqual(saw["numStartups"], 7)
        self.assertIs(saw["hasCompletedOnboarding"], True)
        self.assertIs(saw["hasSeenAutoDefaultNudge"], True)
        self.assertEqual(saw["projects"], {
            "/srv/beta": {"hasTrustDialogAccepted": False},
            str(self.cwd): {"allowedTools": ["Bash"], "hasTrustDialogAccepted": True}})
        self.assertEqual(json.loads(self.config.read_text()), saw)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)

    def test_a_login_with_no_config_gets_one_of_its_own_with_the_dark_theme(self):
        saw = self.opened()
        self.assertEqual(saw, {"theme": "dark", "hasCompletedOnboarding": True,
                               "hasSeenAutoDefaultNudge": True,
                               "projects": {str(self.cwd): {"hasTrustDialogAccepted": True}}})
        # it will hold the owner's login: nobody else reads it
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_a_named_login_opens_with_the_usual_logins_mcp_servers(self):
        # `ak browser mcp-register` writes the usual login's; each replaces one of its name.
        servers = {"browser": {"type": "http", "url": "http://127.0.0.1:8931/mcp"},
                   "desktop": {"type": "stdio", "command": "desktop-mcp", "args": []}}
        own = {"type": "stdio", "command": "notes-mcp"}
        self.home.write(".claude.json", {"userID": "usual-user", "mcpServers": servers})
        self.home.write(".claude-harbor/.claude.json", {"userID": "harbor-user", "mcpServers": {
            "browser": {"type": "http", "url": "http://127.0.0.1:1/gone"}, "notes": own}})
        saw = self.opened(AGENTKIT_ACCOUNT="harbor")
        self.assertEqual(saw["userID"], "harbor-user")
        self.assertEqual(saw["mcpServers"], {"notes": own, **servers})
        self.assertEqual(json.loads(self.config.read_text()),
                         {"userID": "usual-user", "mcpServers": servers})

    def test_settings_that_cannot_be_read_print_no_line_and_start_nothing(self):
        for relative, held in UNREADABLE:
            with self.subTest(file=relative, held=held):
                self.reset()
                path = self.home.write(relative, held)
                starts = len(self.home.calls("claude"))
                printed = self.line()
                self.assertEqual(printed.out, "")
                self.assertRefused(printed, path, held, starts)

    def test_a_line_whose_settings_went_bad_after_it_was_printed_starts_nothing(self):
        for relative, held in UNREADABLE:
            with self.subTest(file=relative, held=held):
                self.reset()
                printed = self.line()
                self.assertEqual(printed.code, 0, printed.err)
                path = self.home.write(relative, held)
                starts = len(self.home.calls("claude"))
                self.assertRefused(self.launch(printed.out), path, held, starts)


if __name__ == "__main__":
    unittest.main()
