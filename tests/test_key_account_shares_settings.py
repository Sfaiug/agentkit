"""A seat or turn on a named login shares the usual login's settings and conversations.

A harness's settings are its own, changed in any of its sessions: its settings screen, or its
model asked to.  So every login of Claude Code, and every login of Grok Build, reads one set of
settings files, and a change made on any login reaches every session and worker on every login
and outlasts their launches.  A named login's settings files are links to the usual login's,
made by the first seat or worker turn on it, whether the usual login has those files yet or
not; its conversations are the usual login's, and its login stays its own.  A launch on the
usual login leaves every login's files alone.

Claude Code: a named login's own settings file gives way to the link, no launch writes the
usual file, and settings already reaching the usual file through other links stay as they are.
Grok Build: a first launch carries into the usual files only the values they lack, leaves one
lacking nothing byte for byte, and moves the named login's file in as written where the usual
login has none; settings it cannot read fail the launch, both files kept.

Black-box: the adapters beside the program `AK_BIN` names, as tests/fixtures/hookdrive.py finds
them, open seats (`interactive`) and run worker turns (`run`) in a Home of tests/fixtures/akbin.py
holding a usual and two named logins, with a fake harness first on PATH.  Go's launch line
answers to this key.  This test fails against `/bin/false`.
"""

import json
import os
from pathlib import Path
import sys
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import ROOT

NAMED, OTHER = "harbor", "quay"
DAY = 86400
# A turn's harness: it writes down the home it started on and the settings files and
# conversations it found there, saves $SAVE as each settings file through the path it read, as
# its settings screen does, and begins a conversation named after that home.
FAKE = """#!{python}
import json, os
from pathlib import Path
home = Path(os.environ.get({variable!r}) or Path.home() / {usual!r})
found = {{}}
for name in {files!r}:
    path = home / name
    found[name] = path.read_text() if path.exists() else None
    if os.environ.get("SAVE"):
        path.write_text(os.environ["SAVE"])
kept = home / {conversations!r} / "acme"
seen = sorted(path.name for path in kept.glob("*"))
kept.mkdir(parents=True, exist_ok=True)
(kept / home.name).write_text("hi\\n")
Path({saw!r}).write_text(json.dumps({{"home": str(home), "settings": found,
                                     "conversations": seen}}))
"""


class Logins:
    """What every harness's launches answer.  A subclass names the harness's adapter and
    program, the variable naming the home it runs on and its usual home, the settings files
    and the conversations directory kept there, its login's file, and `text`, settings holding
    a value."""
    checked = {}    # what the harness's plugin tells its adapter it checked

    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.saw = home.root / "saw.json"
        home.fake(self.program, FAKE.format(
            python=sys.executable, variable=self.variable, usual=self.usual, files=self.files,
            conversations=self.conversations, saw=str(self.saw)))
        self.rulebook = home.write("acme-rules.md", "rules\n")
        self.prompt = home.write("prompt.md", "go\n")
        for login in ("", NAMED, OTHER):
            home.write(f"{self.name(login)}/{self.login}", {"acme": login or "usual"})

    def name(self, login):
        """A login's home under HOME; "" is the usual login."""
        return f"{self.usual}-{login}" if login else self.usual

    def paths(self, login):
        return [self.home.path / self.name(login) / name for name in self.files]

    def write(self, login, text):
        """Give a login settings files of its own holding `text`, a day old; None, none."""
        for name in self.files:
            (self.home.path / self.name(login) / name).unlink(missing_ok=True)
            if text is not None:
                self.home.write(f"{self.name(login)}/{name}", text, ago=DAY)

    def launch(self, verb, login, **env):
        args = ["acme-7", "high"]
        if verb == "run":
            args += [self.home.path, self.prompt, self.home.root / "out"]
        return self.home.run(str(ROOT / "adapters" / f"{self.harness}.sh"), verb,
                             *map(str, args), env={
                                 "AGENTKIT_ACCOUNT": login or None, "AGENTKIT_SESSION": "acme",
                                 "AGENTKIT_RULEBOOK": str(self.rulebook), **self.checked, **env})

    def seat(self, login):
        done = self.launch("interactive", login)
        self.assertEqual(done.code, 0, done.err)

    def turn(self, login, save=None):
        """A worker turn on a login, its harness saving `save` as its settings: what it found."""
        self.saw.unlink(missing_ok=True)
        done = self.launch("run", login, SAVE=save)
        self.assertEqual(done.code, 0, done.err)
        saw = json.loads(self.saw.read_text())
        self.assertEqual(saw.pop("home"), str(self.home.path / self.name(login)))
        return saw

    def found(self, text):
        return {name: text for name in self.files}

    def state(self, *logins):
        """Each settings file of these logins: whether it is a link, its bytes, its last write."""
        return [(path.is_symlink(), path.read_bytes(), path.stat().st_mtime_ns)
                for login in logins for path in self.paths(login)]

    def assertLinked(self, login):
        for path, usual in zip(self.paths(login), self.paths("")):
            self.assertTrue(path.is_symlink(), f"{path} is not a link")
            self.assertEqual(path.resolve(), usual.resolve())

    def test_the_first_seat_or_turn_on_a_named_login_links_settings_not_there_yet(self):
        self.seat(NAMED)
        self.turn(OTHER, save=self.text("dark"))     # its settings screen, the first time
        for login in (NAMED, OTHER):
            self.assertLinked(login)
        self.assertEqual([path.read_text() for path in self.paths("")],
                         [self.text("dark")] * len(self.files))
        for login in ("", NAMED, OTHER):
            own = self.home.path / self.name(login) / self.login
            self.assertFalse(own.is_symlink(), own)
            self.assertEqual(json.loads(own.read_text()), {"acme": login or "usual"})

    def test_a_change_made_on_either_login_reaches_every_login_and_outlasts_launches(self):
        self.write("", self.text("dark"))
        self.seat(NAMED)
        for saver, value in ((NAMED, "light"), ("", "dim")):
            self.turn(saver, save=self.text(value))
            for login in (NAMED, OTHER, ""):
                with self.subTest(saver=saver, login=login):
                    self.seat(login)
                    self.assertEqual(self.turn(login)["settings"], self.found(self.text(value)))
        for login in (NAMED, OTHER):
            self.assertLinked(login)

    def test_a_launch_on_the_usual_login_leaves_every_login_s_files_alone(self):
        for login in ("", NAMED):
            self.write(login, self.text(login or "usual"))
        before = self.state("", NAMED)
        self.seat("")
        self.assertEqual(self.turn("")["settings"], self.found(self.text("usual")))
        self.assertEqual(self.state("", NAMED), before)

    def test_a_named_login_s_conversations_are_the_usual_login_s(self):
        begun = f"{self.conversations}/acme/begun"
        self.home.write(f"{self.usual}/{begun}", "hi\n")
        self.seat(NAMED)
        self.assertTrue((self.home.path / self.name(NAMED) / begun).is_file())
        self.assertEqual(self.turn(OTHER)["conversations"], ["begun"])
        self.assertEqual(self.turn("")["conversations"], sorted(["begun", self.name(OTHER)]))


class ClaudeCode(Logins, unittest.TestCase):
    harness, program, variable, usual = "claude", "claude", "CLAUDE_CONFIG_DIR", ".claude"
    files, conversations, login = ("settings.json",), "projects", ".credentials.json"
    checked = {"AGENTKIT_CLAUDE_CHECKED": "1"}

    def text(self, value):
        return json.dumps({"theme": value}) + "\n"

    def test_no_launch_writes_the_usual_file_and_a_login_s_own_file_gives_way(self):
        self.write("", self.text("dark"))
        self.write(NAMED, self.text("light"))
        before = self.state("")
        for login in (NAMED, OTHER):
            self.seat(login)
            self.assertEqual(self.turn(login)["settings"], self.found(self.text("dark")))
            self.assertLinked(login)
        self.assertEqual(self.state(""), before)

    def test_settings_already_reaching_the_usual_file_through_other_links_stay(self):
        (usual,), (own,) = self.paths(""), self.paths(NAMED)
        dotfiles = self.home.write("dotfiles/claude.json", self.text("dark"))
        # both linked to one dotfiles file, or the usual one through the named one, there or not
        for case, targets in enumerate(((dotfiles, dotfiles), (own, dotfiles), (own, None))):
            with self.subTest(case=case):
                for path, target in zip((usual, own), targets):
                    path.unlink(missing_ok=True)
                    if target:
                        path.symlink_to(target)
                links = [(path.readlink() if path.is_symlink() else path.exists())
                         for path in (usual, own)]
                self.seat(NAMED)
                self.assertEqual(self.turn(NAMED)["settings"],
                                 self.found(usual.read_text() if usual.exists() else None))
                self.assertEqual([(path.readlink() if path.is_symlink() else path.exists())
                                  for path in (usual, own)], links)


class GrokBuild(Logins, unittest.TestCase):
    harness, program, variable, usual = "grokbuild", "grok", "GROK_HOME", ".grok"
    files, conversations, login = ("config.toml", "pager.toml"), "sessions", "auth.json"

    def text(self, value):
        return f'[ui]\ntheme = "{value}"\n'

    def test_a_first_launch_carries_over_only_what_the_usual_files_lack_as_written(self):
        own = "# harbor's own\n[ui]\nvim_mode = true\nshow_timestamps = true\n"
        lacks_nothing = "# the usual\n[ui]\nvim_mode = false\nshow_timestamps = false\n"
        for launch, login, usual, after in (
                # lacking a value: that one is added, and the usual file's own values kept
                (self.turn, NAMED, "[ui]\nvim_mode = false\n",
                 {"ui": {"vim_mode": False, "show_timestamps": True}}),
                # lacking nothing: byte for byte
                (self.seat, OTHER, lacks_nothing, lacks_nothing),
                # none there: the named login's own, as written
                (self.turn, "pier", None, own)):
            with self.subTest(login=login):
                self.write("", usual)
                self.write(login, own)
                launch(login)
                self.assertLinked(login)
                for path in self.paths(""):
                    text = path.read_text()
                    self.assertEqual(text if isinstance(after, str) else tomllib.loads(text),
                                     after)

    def test_settings_it_cannot_read_fail_the_launch_and_both_files_are_kept(self):
        self.write("", self.text("dark"))
        self.write(NAMED, "[invalid")
        before = self.state("", NAMED)
        for verb in ("interactive", "run"):
            with self.subTest(verb=verb):
                self.assertNotEqual(self.launch(verb, NAMED).code, 0)
                self.assertEqual(self.state("", NAMED), before)


if __name__ == "__main__":
    unittest.main()
