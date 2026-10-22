"""`adapters/claude.sh hooks` wires ak's hooks into Claude Code's settings, once.

Claude Code tells ak what a seat is doing only through the hooks in ~/.claude/settings.json:
seat-state.sh on each event that starts or ends a turn, raises or answers a dialog, or
compacts, and orchestrator-stop.sh where a turn ends or a question is about to go up.  Each
install on a host that runs seats asks for them again, so a second time must change nothing: a
second entry would run a hook twice, and a backup would pile up beside a file nothing changed.
Black-box: the adapter shipped beside the program `AK_BIN` names (or in $AGENTKIT_ADAPTER_DIR)
runs in a throwaway HOME through tests/fixtures/akbin.py, and this test fails against
`/bin/false`.
"""

import json
import os
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, Home

ADAPTERS = (Path(os.environ["AGENTKIT_ADAPTER_DIR"]) if os.environ.get("AGENTKIT_ADAPTER_DIR")
            else Path(AK).resolve().parents[1] / "adapters")
SETTINGS = ".claude/settings.json"
STATE, STOP = "seat-state.sh", "orchestrator-stop.sh"
# Each event's groups, in order: the hook scripts each runs, and the tools it is matched to.
WIRED = {"SessionStart": [((STATE,), None)], "UserPromptSubmit": [((STATE,), None)],
         "Stop": [((STATE,), None), ((STOP,), None)], "Notification": [((STATE,), None)],
         "PermissionRequest": [((STATE,), None)],
         "PostToolUse": [((STATE,), "AskUserQuestion|ExitPlanMode")],
         "PreCompact": [((STATE,), None)], "PostCompact": [((STATE,), None)],
         "PreToolUse": [((STOP,), "AskUserQuestion")]}
# The heard events run their hook in the background, where it holds up nothing.
HEARD = ("PermissionRequest", "PostToolUse", "PreCompact", "PostCompact")


class ClaudeHooksWired(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.settings = cls.home.path / SETTINGS
        cls.first = cls.home.run("bash", str(ADAPTERS / "claude.sh"), "hooks")
        cls.wired = cls.settings.read_bytes() if cls.settings.is_file() else b""
        cls.backups_after_first = cls.backups()
        cls.home.write(SETTINGS, cls.wired.decode(), ago=86400)
        cls.stamped = cls.settings.stat().st_mtime_ns
        cls.second = cls.home.run("bash", str(ADAPTERS / "claude.sh"), "hooks")

    @classmethod
    def backups(cls):
        return sorted(path.name for path in cls.settings.parent.glob("settings.json.bak-*"))

    def script(self, handler):
        """The hook script a handler runs, as long as it is `bash` on an absolute path that is
        there."""
        program, _, path = handler["command"].partition(" ")
        self.assertEqual(program, "bash")
        self.assertTrue(Path(path).is_absolute() and Path(path).is_file(), path)
        self.assertEqual(Path(path).resolve(), (ADAPTERS.parent / "hooks" / Path(path).name)
                         .resolve())
        return Path(path).name

    def test_each_event_runs_exactly_its_hook_scripts(self):
        self.assertEqual(self.first.code, 0, self.first.err)
        data = json.loads(self.wired)
        self.assertIsInstance(data, dict)
        self.assertEqual(set(data["hooks"]), set(WIRED))
        for event, groups in WIRED.items():
            with self.subTest(event=event):
                found = [(tuple(self.script(handler) for handler in group["hooks"]),
                          group.get("matcher")) for group in data["hooks"][event]]
                self.assertEqual(found, groups)

    def test_each_handler_is_a_command_run_in_the_background_only_where_it_is_heard(self):
        for event, groups in json.loads(self.wired)["hooks"].items():
            for handler in (handler for group in groups for handler in group["hooks"]):
                with self.subTest(event=event, command=handler["command"]):
                    self.assertEqual(handler["type"], "command")
                    self.assertEqual(handler.get("async", False), event in HEARD)
                    self.assertEqual(set(handler) - {"type", "command", "async"}, set())

    def test_a_first_wiring_backs_up_nothing_where_there_was_no_settings_file(self):
        self.assertEqual(self.backups_after_first, [])

    def test_wiring_again_says_they_already_run_and_leaves_the_file_untouched(self):
        self.assertEqual(self.second.code, 0, self.second.err)
        self.assertIn("already runs", self.second.out)
        self.assertEqual(self.settings.read_bytes(), self.wired)
        self.assertEqual(self.settings.stat().st_mtime_ns, self.stamped)
        self.assertEqual(self.backups(), [])


if __name__ == "__main__":
    unittest.main()
