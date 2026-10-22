"""Wiring ak's Claude hooks merges into the owner's settings and never loses what is there.

ak registers its hooks in ~/.claude/settings.json, the file that also holds the owner's own
Claude Code settings and hooks.  The adapter's `hooks` verb, which install.sh runs for every
harness, must keep each key and hook the owner wrote and back the file up before it first changes
it.  An entry an older install left must be repointed at this install, not doubled; a handler of
ak's must not take on another tool's matcher; and a file that is not a settings object is
refused, not replaced, so a typo never costs the owner their settings.  Black-box: the adapter
beside the program `AK_BIN` names (or `AK_ROOT`'s) runs in a throwaway HOME and is judged by its
exit code, what it prints and the files it leaves; this test fails against `/bin/false`.
"""

from datetime import datetime, timezone
import json
import os
import re
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, Done, Home

ROOT = Path(os.environ.get("AK_ROOT") or Path(AK).resolve().parents[1])
SEAT_STATE = f"bash {ROOT}/hooks/seat-state.sh"
STOP_RULE = f"bash {ROOT}/hooks/orchestrator-stop.sh"
STATED = ("SessionStart", "UserPromptSubmit", "Stop", "Notification", "PermissionRequest",
          "PostToolUse", "PreCompact", "PostCompact")

MINE = {"hooks": [{"type": "command", "command": "bash /x/mine.sh"}]}
# Spaced as a person types it, so a copy that rewrote the file would not be byte-equal.
OWNERS = '{ "theme": "light",\n  "hooks": { "Stop": [' + json.dumps(MINE) + "] } }\n"
LINT = {"type": "command", "command": "bash /x/lint.sh"}
# What an install from another checkout wrote, before seat-state.sh took idle-compact-stop.sh's
# place on Stop; its PostToolUse entry shares a group with the owner's linter.
OLDER = json.dumps({"hooks": {
    "PostToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": "bash /old/agentkit/hooks/seat-state.sh"}, LINT]}],
    "Stop": [{"hooks": [
        {"type": "command", "command": "bash /old/agentkit/hooks/idle-compact-stop.sh"}]}]}})


class HooksMerge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.claude = cls.home.path / ".claude"
        cls.settings = cls.claude / "settings.json"

    def setUp(self):
        shutil.rmtree(self.claude, ignore_errors=True)

    def install(self, settings):
        """Give the owner `settings` as their file's text, then wire ak's hooks over it."""
        self.home.write(".claude/settings.json", settings)
        adapter = ROOT / "adapters" / "claude.sh"
        if not adapter.is_file():
            return Done(127, "", f"no adapter at {adapter}\n")
        return self.home.run(str(adapter), "hooks")

    def wired(self):
        done = self.install(OLDER)
        self.assertEqual(done.code, 0, done.err)
        return json.loads(self.settings.read_text())["hooks"]

    def test_the_owners_keys_and_hooks_stay_and_the_original_is_backed_up_once(self):
        days = {datetime.now(timezone.utc).strftime("%Y%m%d")}
        done = self.install(OWNERS)
        days.add(datetime.now(timezone.utc).strftime("%Y%m%d"))
        self.assertEqual(done.code, 0, done.err)
        data = json.loads(self.settings.read_text())
        self.assertEqual(data["theme"], "light")
        hooks = data["hooks"]
        self.assertIn(MINE, hooks["Stop"])
        for event in STATED:
            with self.subTest(event=event):
                self.assertIn(SEAT_STATE, commands(hooks, event))
        for event in ("Stop", "PreToolUse"):
            with self.subTest(event=event):
                self.assertIn(STOP_RULE, commands(hooks, event))
        backups = sorted(self.claude.glob("settings.json.bak-*"))
        self.assertEqual(len(backups), 1, backups)
        stamp = re.fullmatch(r"settings\.json\.bak-(\d{8})", backups[0].name)
        self.assertIsNotNone(stamp, backups[0].name)
        self.assertIn(stamp.group(1), days)
        self.assertEqual(backups[0].read_text(), OWNERS)

    def test_a_handler_sharing_another_tools_group_moves_to_a_group_of_its_own(self):
        self.assertEqual(self.wired()["PostToolUse"], [
            {"matcher": "Bash", "hooks": [LINT]},
            {"matcher": "AskUserQuestion|ExitPlanMode",
             "hooks": [{"type": "command", "command": SEAT_STATE, "async": True}]}])

    def test_an_older_installs_entries_run_this_installs_hooks_instead_of_being_doubled(self):
        hooks = self.wired()
        self.assertEqual(hooks["Stop"][0], {"hooks": [{"type": "command",
                                                       "command": SEAT_STATE}]})
        self.assertEqual(commands(hooks, "Stop").count(SEAT_STATE), 1)
        everything = {command for event in hooks for command in commands(hooks, event)}
        self.assertEqual(everything, {SEAT_STATE, STOP_RULE, LINT["command"]})

    def test_a_file_that_is_not_json_is_refused_and_left_as_it_was(self):
        done = self.install("{bad")
        self.assertEqual(done.code, 1, done.out)
        for said in (str(self.settings), "is not valid JSON", "left alone"):
            self.assertIn(said, done.err)
        self.assertEqual(self.settings.read_text(), "{bad")
        self.assertEqual(sorted(p.name for p in self.claude.iterdir()), ["settings.json"])

    def test_a_file_that_is_not_a_json_object_is_refused_and_left_as_it_was(self):
        done = self.install("[]")
        self.assertEqual(done.code, 1, done.out)
        self.assertIn(f"{self.settings} is not a JSON object; left alone", done.err)
        self.assertEqual(self.settings.read_text(), "[]")
        self.assertEqual(sorted(p.name for p in self.claude.iterdir()), ["settings.json"])


def commands(hooks, event):
    """Each command an event runs, in the order Claude Code runs them."""
    return [entry.get("command") for group in hooks.get(event) or []
            for entry in group.get("hooks") or []]


if __name__ == "__main__":
    unittest.main()
