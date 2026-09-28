"""A relaunched seat keeps the name ak gave it; fake tmux, titles and HOME."""

import json
import os
import re
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, orch, watch


class FakeTitles:
    """Title hooks over JSON files under HOME, on a real harness's screen.

    One file per conversation: {"title": ..., "manual": ...}. Only a manual title
    names or confirms the seat; a missing file is unreadable. `at_launch` decides
    what a launch records, the way the adapter manifest does for a real harness.
    """

    def __init__(self, real, home, at_launch):
        self._real = real
        self._home = home
        self._at_launch = at_launch

    def __getattr__(self, name):
        return getattr(self._real, name)

    @property
    def title_facts(self):
        return {"at_launch": self._at_launch, "unreadable": False}

    def title_command(self, name):
        return f"/rename {name}"

    def sync_title(self, name, record):
        return None

    def title_ready(self, record, state):
        return state in ("at_prompt", "draft") and self.session_title(record) is not None

    def session_title(self, record):
        try:
            data = json.loads((self._home / f"{record['conversation']}.json").read_text(
                encoding="utf-8"))
        except (OSError, ValueError, KeyError, AttributeError):
            return None
        if data.get("manual") is not True:
            return ""
        title = data.get("title")
        return title if isinstance(title, str) and title.strip() else ""


class RelaunchKeepsName(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "AK_NOTIFY_SINK": str(self.root / "notices")}))
        self.titles = self.root / "titles"
        self.titles.mkdir()
        self.sid = "fake-conversation"
        self.seat = {"name": "lagoon", "path": str(self.root), "created": 100,
                     "attached": True, "exited": False, "legacy": False}
        self.pane = self.fixture("idle")
        self.typed, self.keys = [], []
        self.confirm = True
        self.at_launch = False
        config.save_session(self.cfg, "lagoon", "grok", ["grok"], {
            "cwd": str(self.root), "conversation": self.sid, "id_source": "launcher",
            "session_title": "lagoon"})
        self.title("lagoon")
        real_plugin = orch.seat_plugin

        def titles(record):
            plugin = real_plugin(record)
            if record.get("orchestrator") == "grok":
                return FakeTitles(plugin, self.titles, self.at_launch)
            return plugin

        self.stack.enter_context(patch.object(orch, "seat_plugin", side_effect=titles))
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        self.stack.enter_context(patch.object(watch, "SENT_WAIT", watch.SENT_POLL))
        self.stack.enter_context(patch.object(watch.time, "sleep"))
        for method in ("poll_worker_token", "seat_account", "stop_nudge", "announce_state"):
            self.stack.enter_context(patch.object(watch, method, return_value=False))

    def fixture(self, kind):
        return (REPO / "tests/fixtures" / f"grok-title-{kind}-pane.txt").read_text()

    def title(self, name, *, manual=True):
        (self.titles / f"{self.sid}.json").write_text(json.dumps(
            {"title": name, "manual": manual}))

    def record(self):
        return config.session_records()[self.seat["name"]]

    def compose(self, text):
        rows = self.pane.splitlines()
        at = next(i for i in reversed(range(len(rows)))
                  if watch.strip_sgr(rows[i]).strip().startswith("│ ❯"))
        rows[at] = "  │ ❯ " + text.ljust(90) + " │"
        self.pane = "\n".join(rows) + "\n"

    def tmux(self, *args, **kwargs):
        if args[0] == "rename-session":
            self.seat = dict(self.seat, name=args[-1])
        elif args[0] == "capture-pane":
            self.assertEqual(args[-1], f"={self.seat['name']}:")
            return 0, self.pane
        elif args[0] == "send-keys":
            self.assertEqual(args[2], f"={self.seat['name']}:")
            self.keys.append(args[-1])
            if "-l" in args:
                self.typed.append(args[-1])
                self.compose(args[-1])
            elif args[-1] == "Enter":
                self.assertTrue(self.typed[-1].startswith("/rename "))
                self.pane = self.fixture("idle")
                if self.confirm:
                    self.title(self.typed[-1].removeprefix("/rename "))
        return 0, ""

    def tick(self):
        state = watch.load_state()
        watch.health(self.cfg, state, False, lambda _: None)
        watch.save_state(state)

    def relaunch(self):
        with patch.object(orch, "start"):
            orch.launch(self.seat["name"], "grok", self.root, ["grok"], self.sid)

    def test_held_rename_then_relaunch_keeps_the_new_name_and_types_it(self):
        self.pane = (REPO / "tests/fixtures/grok-working-pane.txt").read_text()
        orch.rename("lagoon", "quay")
        self.assertEqual(self.keys, [])
        self.assertNotIn("title_sync", self.record())
        self.relaunch()
        self.assertEqual(self.record()["title_superseded"], ["lagoon"])
        self.pane = self.fixture("idle")
        self.tick()
        self.tick()
        self.assertEqual(self.seat["name"], "quay")
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "quay")

    def test_auto_named_relaunch_before_its_title_took_stays_auto_named(self):
        config.update_session("lagoon", session_title=None, unnamed=True,
                              title_sync={"name": "lagoon", "tries": 1, "pending": False})
        self.title("", manual=False)
        self.relaunch()
        self.assertNotIn("title_sync", self.record())
        self.tick()
        self.tick()
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertTrue(self.record().get("unnamed"))
        self.assertEqual(self.typed, ["/rename lagoon"])
        self.assertEqual(self.record()["session_title"], "lagoon")

    def test_owner_rename_after_relaunch_still_renames_the_seat(self):
        self.relaunch()
        self.title("Fix API")
        self.tick()
        self.assertEqual(self.seat["name"], "fix-api")
        self.assertEqual(self.typed, ["/rename fix-api"])
        self.assertEqual(self.record()["session_title"], "fix-api")

    def test_owner_rename_while_down_still_renames_the_seat(self):
        self.title("Fix API")
        self.relaunch()
        self.tick()
        self.assertEqual(self.seat["name"], "fix-api")
        self.assertEqual(self.typed, ["/rename fix-api"])
        self.assertEqual(self.record()["session_title"], "fix-api")


class RelaunchClaude(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "AK_NOTIFY_SINK": str(self.root / "notices")}))
        self.seat = {"name": "lagoon", "path": str(self.root), "created": 100,
                     "attached": True, "exited": False, "legacy": False}
        self.pane = self.fixture("prompt")
        self.typed = []
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        self.stack.enter_context(patch.object(watch, "SENT_WAIT", watch.SENT_POLL))
        self.stack.enter_context(patch.object(watch.time, "sleep"))
        for method in ("poll_worker_token", "seat_account", "stop_nudge", "announce_state"):
            self.stack.enter_context(patch.object(watch, method, return_value=False))
        config.save_session(self.cfg, "lagoon", "opus", ["opus"], {
            "cwd": str(self.root), "conversation": "fake-conversation",
            "id_source": orch.LAUNCHER, "session_title": "lagoon"})
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.root))
        self.transcript = self.root / ".claude/projects" / slug / "fake-conversation.jsonl"
        self.transcript.parent.mkdir(parents=True)
        self.transcript.touch()

    def fixture(self, kind):
        return (REPO / "tests/fixtures" / f"claude-{kind}-pane.txt").read_text()

    def title(self, name):
        with self.transcript.open("a") as handle:
            handle.write(json.dumps({"type": "custom-title", "customTitle": name,
                                     "sessionId": "fake-conversation"}) + "\n")

    def record(self):
        return config.session_records()[self.seat["name"]]

    def tmux(self, *args, **kwargs):
        if args[0] == "rename-session":
            self.seat = dict(self.seat, name=args[-1])
        elif args[0] == "capture-pane":
            return 0, self.pane
        elif args[0] == "send-keys":
            self.assertEqual(args[2], f"={self.seat['name']}:")
            if "-l" in args:
                self.typed.append(args[-1])
                self.pane = self.pane.replace("❯ \n", f"❯ {args[-1]}\n")
            elif args[-1] == "Enter":
                self.pane = self.pane.replace(f"❯ {self.typed[-1]}\n", "❯ \n")
                self.title(self.typed[-1].removeprefix("/rename "))
        return 0, ""

    def tick(self):
        state = watch.load_state()
        watch.health(self.cfg, state, False, lambda _: None)
        watch.save_state(state)

    def test_launch_records_without_typing(self):
        self.title("lagoon")
        orch.launch("lagoon", "opus", self.root, ["claude"], "fake-conversation")
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.assertNotIn("title_sync", self.record())
        self.tick()
        self.tick()
        self.assertEqual(self.typed, [])
        self.assertEqual(self.record()["session_title"], "lagoon")

    def test_owner_rename_after_relaunch_still_renames_the_seat(self):
        self.title("lagoon")
        orch.launch("lagoon", "opus", self.root, ["claude"], "fake-conversation")
        self.title("Fix API")
        self.tick()
        self.assertEqual(self.seat["name"], "fix-api")
        self.assertEqual(self.typed, ["/rename fix-api"])
        self.assertEqual(self.record()["session_title"], "fix-api")


if __name__ == "__main__":
    unittest.main()
