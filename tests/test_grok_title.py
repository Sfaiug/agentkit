"""Grok's manual titles follow the owned seat both ways; fake tmux and temporary HOME."""

import json
import os
import unittest
from unittest.mock import patch
from urllib.parse import quote

from test_v4n import REPO, Sandbox
from agentkit import config, orch, watch
from agentkit.harness import grokbuild


class GrokTitle(Sandbox):
    def setUp(self):
        super().setUp()
        self.home = self.root / ".grok"
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "GROK_HOME": str(self.home), "AK_NOTIFY_SINK": str(self.root / "notices")}))
        self.seat = {"name": "lagoon", "path": str(self.root), "created": 100,
                     "attached": True, "exited": False, "legacy": False}
        self.sid = self.summary_fixture()["info"]["id"]
        self.pane = self.fixture("idle")
        self.typed, self.keys = [], []
        self.confirm, self.drop_enter = True, False
        config.save_session(self.cfg, "lagoon", "grok", ["grok"], {
            "cwd": str(self.root), "conversation": self.sid, "id_source": "launcher",
            "session_title": "lagoon"})
        self.title("lagoon")
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        self.stack.enter_context(patch.object(watch, "SENT_WAIT", watch.SENT_POLL))
        self.stack.enter_context(patch.object(watch.time, "sleep"))
        for method in ("poll_worker_token", "seat_account", "stop_nudge", "announce_state"):
            self.stack.enter_context(patch.object(watch, method, return_value=False))

    def fixture(self, kind):
        return (REPO / "tests/fixtures" / f"grok-title-{kind}-pane.txt").read_text()

    def summary_fixture(self, kind="manual"):
        return json.loads((REPO / "tests/fixtures" / f"grok-title-{kind}.json").read_text())

    def summary_path(self, sid=None, cwd=None):
        return (self.home / "sessions" / quote(str(cwd or self.root), safe="") /
                (sid or self.sid) / "summary.json")

    def title(self, name, *, manual=True, sid=None, cwd=None):
        data = self.summary_fixture("manual" if manual else "auto")
        data["info"] = {"id": sid or self.sid, "cwd": str(cwd or self.root)}
        data.update(generated_title=name, session_summary=name)
        path = self.summary_path(sid, cwd)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

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
            elif args[-1] == "Enter" and not self.drop_enter:
                # The only input accepted by this fake is the local slash command.
                self.assertTrue(self.typed[-1].startswith("/rename "))
                self.pane = self.fixture("accepted")
                if self.confirm:
                    self.title(self.typed[-1].removeprefix("/rename "))
        return 0, ""

    def tick(self):
        state = watch.load_state()
        watch.health(self.cfg, state, False, lambda _: None)
        watch.save_state(state)

    def test_ak_rename_types_once_and_requires_the_manual_receipt(self):
        self.confirm = False
        orch.rename("lagoon", "quay")
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.title("quay")
        self.tick()
        self.tick()
        self.assertEqual(self.keys, ["/rename quay", "Enter"])
        self.assertEqual(self.record()["session_title"], "quay")
        self.assertNotIn("title_sync", self.record())

    def test_new_launch_waits_for_its_summary_and_pins_the_title(self):
        with patch.object(orch, "start"):
            orch.launch("lagoon", "grok", self.root, ["grok"], self.sid)
        self.assertNotIn("session_title", self.record())
        self.summary_path().unlink()
        self.tick()
        self.assertEqual(self.keys, [])
        self.title("", manual=False)
        self.tick()
        self.tick()
        self.assertEqual(self.typed, ["/rename lagoon"])
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.assertIs(json.loads(self.summary_path().read_text())["title_is_manual"], True)

    def test_auto_name_uses_the_same_delivery(self):
        config.update_session("lagoon", unnamed=True)
        orch.rename("lagoon", "fix-api", auto=True)
        self.assertEqual(self.keys, ["/rename fix-api", "Enter"])
        self.assertEqual(self.record()["session_title"], "fix-api")
        self.assertIs(json.loads(self.summary_path().read_text())["title_is_manual"], True)

    def test_owner_rename_renames_the_seat_and_normalizes_the_title(self):
        self.title("Fix API")
        self.tick()
        self.assertEqual(self.seat["name"], "fix-api")
        self.assertEqual(self.typed, ["/rename fix-api"])
        self.assertEqual(self.record()["session_title"], "fix-api")

    def test_automatic_title_and_reset_never_rename_the_seat(self):
        for marker in (None, False):
            with self.subTest(marker=marker):
                self.title("Generated task title", manual=False)
                data = json.loads(self.summary_path().read_text())
                if marker is not None:
                    data["title_is_manual"] = marker
                    self.summary_path().write_text(json.dumps(data))
                self.tick()
                self.assertEqual(grokbuild.session_title(self.record()), "")
                self.assertEqual(self.seat["name"], "lagoon")
                self.assertEqual(self.keys, [])
        self.summary_path().write_text(json.dumps({**self.summary_fixture("auto"),
            "info": {"id": self.sid, "cwd": str(self.root)}}))
        self.tick()
        self.assertEqual(self.seat["name"], "lagoon")

    def test_matching_automatic_title_cannot_confirm_an_ak_rename(self):
        self.confirm = False
        self.title("quay", manual=False)
        orch.rename("lagoon", "quay")
        self.assertEqual(self.keys, ["/rename quay", "Enter"])
        self.assertEqual(self.record()["session_title"], "lagoon")

    def test_another_sessions_title_changes_nothing(self):
        self.title("foreign-name", sid="00000000-0000-4000-8000-000000000002")
        self.title("other-workspace", cwd=self.root / "other")
        self.tick()
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertEqual(self.keys, [])

    def test_unreadable_or_foreign_summary_is_not_a_receipt(self):
        path = self.summary_path()
        for contents in ("{", "[]", "null", "\udcff", json.dumps(self.summary_fixture())):
            with self.subTest(contents=contents):
                path.write_bytes(contents.encode("utf-8", errors="surrogateescape"))
                self.assertIsNone(grokbuild.session_title(self.record()))
                self.assertIsNone(watch.follow_title(self.seat))
                self.assertFalse(watch.sync_title(self.seat, force=True))
                self.assertEqual(self.keys, [])
        self.title("lagoon")
        self.assertIsNone(grokbuild.session_title({**self.record(), "id_source": "unowned"}))
        self.assertIsNone(grokbuild.session_title({**self.record(), "conversation": None}))

    def test_lost_receipt_does_not_confirm_a_cleared_composer(self):
        self.confirm = False
        def lose_receipt():
            self.summary_path().unlink()
            return True
        with patch.object(watch, "_wait_sent", side_effect=lambda *_: lose_receipt()):
            orch.rename("lagoon", "quay")
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "lagoon")

    def test_responding_turn_waits_for_the_prompt(self):
        self.pane = (REPO / "tests/fixtures/grok-working-pane.txt").read_text()
        orch.rename("lagoon", "quay")
        self.tick()
        self.assertEqual(self.keys, [])
        self.assertNotIn("title_sync", self.record())
        self.pane = self.fixture("idle")
        self.tick()
        self.assertEqual(self.keys, ["/rename quay", "Enter"])

    def test_drafts_and_dialogs_are_untouched(self):
        self.title("", manual=False)
        config.update_session("lagoon", session_title=None)
        for pane in (self.fixture("composed"), self.fixture("working-composed"),
                     (REPO / "tests/fixtures/grok-dialog-pane.txt").read_text()):
            with self.subTest(pane=pane):
                self.pane = pane
                self.assertFalse(watch.sync_title(self.seat, force=True))
                self.assertEqual(self.pane, pane)
                self.assertEqual(self.keys, [])

    def test_pending_boxed_line_gets_only_enter_and_owner_edits_stay(self):
        self.drop_enter = True
        orch.rename("lagoon", "quay", log=lambda _: None)
        self.tick()
        self.assertEqual(self.typed, ["/rename quay"])
        self.compose("/rename quay with my own draft")
        before = list(self.keys)
        self.tick()
        self.assertEqual(self.keys, before)
        self.compose("/rename quay")
        self.drop_enter = False
        self.tick()
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "quay")

    def test_pending_wrapped_line_keeps_its_box_and_owner_continuation(self):
        self.drop_enter = True
        orch.rename("lagoon", "quay", log=lambda _: None)
        self.compose("/rename qu")
        self.pane = self.pane.replace("  ╰", "  │ ay │\n  │ owner draft │\n  ╰")
        before = list(self.keys)
        self.tick()
        self.assertEqual(self.keys, before)
        self.pane = self.pane.replace("  │ owner draft │\n", "")
        self.drop_enter = False
        self.tick()
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "quay")

    def test_default_home_and_custom_grok_home_use_the_same_path_rule(self):
        os.environ.pop("GROK_HOME")
        self.assertEqual(grokbuild.session_title(self.record()), "lagoon")
        self.home = self.root / "custom"
        os.environ["GROK_HOME"] = str(self.home)
        self.title("quay")
        self.assertEqual(grokbuild.session_title(self.record()), "quay")


if __name__ == "__main__":
    unittest.main()
