"""A seat follows its own Claude across /clear; fake processes, tmux and transcripts."""

import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, orch, watch
from agentkit.harness import claude


class SeatFollowsClear(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_SESSION": "lagoon", "AK_RUN_ROLE": "seat",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "IDLE_COMPACT_STATE": "",
            "TMUX": "/fake/agentkit-test,1,0", "TMUX_PANE": "%7",
            "AGENTKIT_ACCOUNT": "", "CLAUDE_CONFIG_DIR": "",
            "AK_NOTIFY_SINK": str(self.root / "notices")}))
        # The shell hook imports config in its own process, so both use this throwaway HOME.
        self.stack.enter_context(patch.object(config, "STATE", self.root / ".agentkit/state"))
        config.ensure_dirs()
        self.seat = {"name": "lagoon", "path": str(self.root), "created": 100,
                     "attached": True, "exited": False, "legacy": False}
        self.table = {101: (1, ["python3", str(REPO / "tools/idle-compact.py"), "--", "claude"]),
                      102: (101, ["claude", "--session-id", "before-clear"]),
                      103: (102, ["sh", "-c", "bash hooks/seat-state.sh"])}
        self.stack.enter_context(patch.object(orch, "processes", side_effect=lambda: self.table))
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "announce_state"))
        self.stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        self.typed = []
        config.save_session(self.cfg, "lagoon", "opus", ["opus"], {
            "cwd": str(self.root), "conversation": "before-clear", "id_source": orch.LAUNCHER,
            "session_title": "lagoon", "account": "default"})
        self.title("before-clear", "lagoon")
        self.title("after-clear", "lagoon")

    def record(self):
        return config.session_records()[self.seat["name"]]

    def title(self, conversation, title):
        path = claude.transcript_path(self.record(), conversation)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(json.dumps({"type": "custom-title", "sessionId": conversation,
                                     "customTitle": title}) + "\n")
        return path

    def payload(self, conversation="after-clear", **extra):
        return {"hook_event_name": "SessionStart", "source": "clear",
                "session_id": conversation,
                "transcript_path": str(claude.transcript_path(self.record(), conversation)), **extra}

    def hook(self, pid=103, **extra):
        claude.capture("lagoon", self.payload(**extra), pid)

    def tmux(self, *args, **kwargs):
        if args[0] == "display-message":
            return 0, f"/fake/agentkit-test\t{self.seat['name']}\t101"
        if args[0] == "rename-session":
            self.seat = dict(self.seat, name=args[-1])
        elif args[0] == "capture-pane":
            return 0, (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()
        elif args[0] == "send-keys":
            if "-l" in args:
                self.typed.append(args[-1])
            elif args[-1] == "Enter":
                self.title(self.record()["conversation"], self.typed[-1].removeprefix("/rename "))
        return 0, ""

    def assert_resume(self, conversation):
        for seats in ([], [dict(self.seat, exited=True)]):
            with self.subTest(seats=seats), patch.object(orch, "sessions", return_value=seats), \
                    patch.object(orch, "launch") as launch:
                self.assertEqual(orch.resume(self.cfg, self.seat["name"], hand_over=False,
                                             log=lambda _: None), "resumed")
                command = launch.call_args.args[3]
                self.assertEqual(command[command.index("--resume") + 1], conversation)
                self.assertEqual(launch.call_args.args[4], conversation)

    def test_own_hook_moves_the_record_and_both_reopen_paths_resume_it(self):
        before = self.record()
        self.hook()
        self.assertEqual(self.record(), {**before, "conversation": "after-clear",
                                         "id_source": claude.SOURCE})
        self.assertTrue(orch.resumable(self.record()))
        self.assertEqual(orch.seat_conversation(orch.records()["lagoon"]), "after-clear")
        self.assert_resume("after-clear")

    def test_new_transcript_names_the_seat_and_old_title_never_renames_it_back(self):
        self.hook()
        self.title("after-clear", "Checkout Bug")
        self.assertEqual(watch.follow_title(self.seat), "checkout-bug")
        self.assertEqual(self.record()["session_title"], "checkout-bug")
        orch.rename("checkout-bug", "quay")
        self.assertEqual(claude.session_title(self.record()), "quay")
        # The frozen transcript still holds agentkit's earlier title, unlike both current names.
        self.assertEqual(claude.session_title({**self.record(), "conversation": "before-clear"}),
                         "lagoon")
        with patch.object(orch, "rename") as rename:
            watch.follow_title(self.seat)
            watch.follow_title(self.seat)
            rename.assert_not_called()
        self.assertEqual(self.typed, ["/rename checkout-bug", "/rename quay"])

    def test_never_cleared_seat_keeps_its_record_title_and_resume(self):
        path = config.session_path("lagoon")
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.hook(conversation="before-clear")
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual(claude.session_title(self.record()), "lagoon")
        self.assert_resume("before-clear")

    def test_nested_claude_and_workers_cannot_move_the_seat(self):
        before = self.record()
        for words in (["claude"], ["claude", "-p"], ["claude", "--print"]):
            with self.subTest(words=words):
                self.table.update({104: (102, words), 105: (104, ["sh", "-c", "hook"])})
                self.hook(pid=105)
                self.assertEqual(self.record(), before)
        with patch.dict(os.environ, {"AK_RUN_ROLE": "worker"}):
            self.hook()
        self.assertEqual(self.record(), before)
        self.table[102] = (101, ["claude", "-p"])
        self.hook()
        self.assertEqual(self.record(), before)

    def test_unrelated_process_subagent_and_wrong_pane_leave_the_record_alone(self):
        before = self.record()
        self.table[201] = (1, ["claude"])
        self.hook(pid=201)
        self.hook(agent_id="fake-agent")
        self.hook(transcript_path=str(self.root / "subagents/agent-fake.jsonl"))
        for fields in ({"TMUX": ""}, {"TMUX_PANE": ""}, {"TMUX": "/fake/other,1,0"}):
            with patch.dict(os.environ, fields):
                self.hook()
        with patch.object(orch, "tmux_out", return_value=(0, "/fake/agentkit-test\tother\t101")):
            self.hook()
        self.assertEqual(self.record(), before)

    def test_renamed_seat_and_named_login_follow_repeated_clears(self):
        orch.rename("lagoon", "quay")
        config.update_session("quay", account="second")
        directory = self.root / ".claude-second"
        directory.mkdir()
        (directory / "projects").symlink_to(self.root / ".claude/projects", target_is_directory=True)
        self.hook()
        self.title("next-clear", "quay")
        self.hook(conversation="next-clear")
        self.assertEqual(self.record()["conversation"], "next-clear")
        self.assertEqual(self.record()["account"], "second")
        self.assertEqual(config.resolve_session("lagoon"), "quay")
        self.assertEqual(claude.session_title(self.record()), "quay")
        self.assert_resume("next-clear")

    def test_shell_hook_captures_before_returning_without_a_status_event(self):
        # Every external process query is fake; no real seat or process table is inspected.
        bindir = self.root / "bin"
        bindir.mkdir()
        fake_tmux = bindir / "tmux"
        fake_tmux.write_text('''#!/bin/bash
if [[ $1 = -L && $2 = agentkit-test ]]; then shift 2; else exit 1; fi
case $1 in
  list-sessions) printf 'lagoon\\t%s\\t100\\t1\\t1\\n' "$HOME" ;;
  list-panes) printf 'lagoon\\t0\\n' ;;
  display-message) printf '/fake/agentkit-test\\tlagoon\\t101\\n' ;;
  *) exit 1 ;;
esac
''')
        fake_ps = bindir / "ps"
        fake_ps.write_text(f'''#!/bin/bash
printf '%s\\n' '101 1 python3 tools/idle-compact.py -- claude' \\
  '102 101 claude --session-id before-clear' '{os.getpid()} 102 sh -c hook'
''')
        for path in (fake_tmux, fake_ps):
            path.chmod(0o755)
        proc = subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")],
                              input=json.dumps(self.payload()), capture_output=True, text=True,
                              env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.record()["conversation"], "after-clear")
        self.assertFalse(config.hook_facts_path("lagoon").exists())

    def test_install_wires_clear_events_to_the_same_seat_hook(self):
        proc = subprocess.run(["bash", str(REPO / "adapters/claude.sh"), "hooks"],
                              capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        hooks = json.loads((self.root / ".claude/settings.json").read_text())["hooks"]
        self.assertEqual(hooks["SessionStart"], hooks["UserPromptSubmit"])
        self.assertIn("hooks/seat-state.sh", json.dumps(hooks["SessionStart"]))


if __name__ == "__main__":
    unittest.main()
