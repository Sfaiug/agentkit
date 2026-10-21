"""Grok Build gets ak's hooks in a file of ak's own; the per-launch harnesses get none written.

A Grok seat's word rides its hooks, which the TUI reads only from its home's hooks directory, so
`adapters/grokbuild.sh hooks` (install.sh runs it, and a seat on an account's login runs it for
that home) writes them into `hooks/agentkit.json` there, beside the user's own files and never
into them.  Grok also runs the hooks it finds in Claude's settings and drops only an identical
(event, command) pair, so its file must name the very commands Claude's hooks do, or each fires
twice.  Codex, Muse and OpenCode are handed their hooks on each launch's command line and
Antigravity takes none: their `hooks` verb writes nothing a stale copy could linger in.

Black-box: the adapters beside the program `AK_BIN` names (or `AK_ROOT`'s) run as install.sh
runs them, in a throwaway HOME; this test fails against `/bin/false`.
"""

import json
import os
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, Home

ADAPTERS = Path(os.environ.get("AK_ROOT") or Path(AK).resolve().parents[1]) / "adapters"
FILE = "hooks/agentkit.json"


def adapter(home, harness, *args, env=None):
    return home.run("bash", str(ADAPTERS / f"{harness}.sh"), *args, env=env)


def files(home):
    """Every file and directory under HOME, with what each file holds."""
    return {str(path.relative_to(home.path)): path.read_bytes() if path.is_file() else None
            for path in home.path.rglob("*")}


def day():
    return time.strftime("%Y%m%d", time.gmtime())     # the Home's clock is UTC


class GrokHooks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The commands Claude's own hooks run, which Grok's file must repeat exactly.
        with Home() as home:
            done = adapter(home, "claude", "hooks")
            assert done.code == 0, done.err
            claude = json.loads((home.path / ".claude/settings.json").read_text())["hooks"]
        named = {event: [entry["command"] for group in claude[event] for entry in group["hooks"]]
                 for event in ("UserPromptSubmit", "Stop")}
        [seat] = named["UserPromptSubmit"]
        [stop] = [command for command in named["Stop"] if command != seat]
        state, gate = ({"type": "command", "command": command} for command in (seat, stop))
        cls.wanted = {"hooks": {
            "UserPromptSubmit": [{"hooks": [state]}],
            "Stop": [{"hooks": [state, gate]}],
            "StopCancelled": [{"hooks": [state]}],
            "StopFailure": [{"hooks": [state]}],
            "Notification": [{"hooks": [state]}],
            "PostToolUse": [{"matcher": "ask_user_question", "hooks": [state]}]}}

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def hooks(self, home=None, env=None):
        done = adapter(home or self.home, "grokbuild", "hooks", env=env)
        self.assertEqual(done.code, 0, done.err)
        return done

    def read(self, grok_home, home=None):
        return json.loads(((home or self.home).path / grok_home / FILE).read_text())

    def test_hooks_are_written_to_aks_own_file_in_the_grok_home_and_nowhere_else(self):
        before = files(self.home)
        self.hooks()
        self.assertEqual(self.read(".grok"), self.wanted)
        self.assertEqual(set(files(self.home)) - set(before),
                         {".grok", ".grok/hooks", ".grok/" + FILE})

    def test_hooks_already_there_are_left_as_they_are(self):
        self.hooks()
        before = files(self.home)
        done = self.hooks()
        self.assertIn("already installed", done.out)
        self.assertEqual(files(self.home), before)

    def test_a_file_that_differs_is_kept_as_the_days_backup_and_rewritten(self):
        self.home.write(".grok/" + FILE, "{}")
        first = day()
        self.hooks()
        backups = [path for path in (self.home.path / ".grok/hooks").iterdir()
                   if path.name != "agentkit.json"]
        self.assertEqual(len(backups), 1, backups)
        self.assertIn(backups[0].name, {f"agentkit.json.bak-{first}",
                                        f"agentkit.json.bak-{day()}"})
        self.assertEqual(backups[0].read_text(), "{}")
        self.assertEqual(self.read(".grok"), self.wanted)

    def test_grok_home_or_an_account_says_which_home_takes_the_file(self):
        cases = {"GROK_HOME names its home": ({"GROK_HOME": "g"}, "g"),
                 "an account has a home of its own": ({"AGENTKIT_ACCOUNT": "be"}, ".grok-be"),
                 "an account's home wins over GROK_HOME":
                     ({"AGENTKIT_ACCOUNT": "be", "GROK_HOME": "g"}, ".grok-be"),
                 # a seat on an account hands its home to what it starts; a call naming no
                 # account must not spend that subscription
                 "an account's home inherited without its name is dropped":
                     ({"GROK_HOME": ".grok-ce"}, ".grok")}
        for case, (env, grok_home) in cases.items():
            with self.subTest(case), Home() as home:
                if "GROK_HOME" in env:
                    env = {**env, "GROK_HOME": str(home.path / env["GROK_HOME"])}
                self.hooks(home, env)
                self.assertEqual(self.read(grok_home, home), self.wanted)
                written = {path.parent.parent.name for path in home.path.rglob("agentkit.json")}
                self.assertEqual(written, {grok_home})

    def test_a_seat_opened_on_an_account_carries_the_hooks_in_that_accounts_home(self):
        rulebook = self.home.write("rb.md", "rb\n")
        done = adapter(self.home, "grokbuild", "interactive", "grok-4", "high",
                       env={"AGENTKIT_ACCOUNT": "be", "AGENTKIT_SESSION": "acme",
                            "AGENTKIT_RULEBOOK": str(rulebook)})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.read(".grok-be"), self.wanted)


class PerLaunchHooks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def test_codex_muse_opencode_and_antigravity_write_nothing(self):
        said = {"codex": "installed per launch", "muse": "given per launch",
                "opencode": "installed per launch", "antigravity": "no hooks installed"}
        for harness, words in said.items():
            with self.subTest(harness):
                before = files(self.home)
                done = adapter(self.home, harness, "hooks")
                self.assertEqual(done.code, 0, done.err)
                self.assertIn(words, done.out)
                self.assertEqual(files(self.home), before)

    def test_opencode_refuses_an_account_and_writes_nothing(self):
        before = files(self.home)
        done = adapter(self.home, "opencode", "hooks", env={"AGENTKIT_ACCOUNT": "be"})
        self.assertEqual(done.code, 1, done.out)
        self.assertIn("refused", done.out + done.err)
        self.assertEqual(files(self.home), before)


if __name__ == "__main__":
    unittest.main()
