"""A seat follows its own Claude across /clear; fake processes, tmux and transcripts."""

import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from fixtures.pane import resolved
from fixtures.sandbox import REPO, Sandbox
from agentkit import config, notify, orch, watch
from agentkit.guard import commands
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
        for method in ("poll_worker_token", "seat_account", "stop_nudge", "announce_state"):
            self.stack.enter_context(patch.object(watch, method, return_value=False))
        self.stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        self.typed = []
        self.pane = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()
        self.bound_pane = "%7"
        self.active_pane = "%7"
        self.panes = {"%7": (101, False), "%8": (201, False), "%9": (301, False)}
        self.server_up = True
        self.tmux_calls = []
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
        self.tmux_calls.append(resolved(args))
        if args[0] == "source-file":
            return (0 if self.server_up else 1), ""
        if args[0] == "display-message":
            pane = self.active_pane if args[3] == f"={self.seat['name']}:" else args[3]
            if pane not in self.panes:
                return 0, ""
            fields = {"socket_path": "/fake/agentkit-test", "session_name": self.seat["name"],
                      "pane_pid": str(self.panes[pane][0]), "pane_id": pane,
                      orch.PANE_OPTION: self.bound_pane}
            out = args[-1]
            for key, value in fields.items():
                out = out.replace(f"#{{{key}}}", value)
            return 0, out.strip()
        if "new-session" in args:
            return 0, ""
        if args[0] == "show-options":
            target = args[args.index("-t") + 1]
            return 0, (self.bound_pane if target in
                       (self.seat["name"], f"={self.seat['name']}:", *self.panes) else "")
        if args[0] == "list-panes":
            self.assertEqual(args, ("list-panes", "-s", "-t", f"={self.seat['name']}:", "-F",
                                    "#{pane_id}\t#{pane_pid}\t#{pane_dead}"))
            return 0, "\n".join(f"{pane}\t{pid}\t{int(dead)}"
                                for pane, (pid, dead) in self.panes.items())
        if args[0] == "respawn-pane":
            target = args[args.index("-t") + 1]
            if target not in (*self.panes, f"={self.seat['name']}:"):
                return 1, "can't find pane"
            return 0, ""
        for command in commands(args):
            if command[0] == "set-option" and orch.PANE_OPTION in command:
                if "-F" in command:
                    target = command[command.index("-t") + 1]
                    self.bound_pane = (self.active_pane if target == f"={self.seat['name']}:"
                                       else target)
                else:
                    self.bound_pane = command[-1]
        if args[0] == "rename-session":
            self.seat = dict(self.seat, name=args[-1])
        elif args[0] == "capture-pane":
            return 0, self.pane
        elif args[0] == "send-keys":
            if "-l" in args:
                self.typed.append(args[-1])
                self.pane = self.pane.replace("❯\u00a0\n", f"❯ {args[-1]}\n")
            elif args[-1] == "Enter":
                self.pane = self.pane.replace(f"❯ {self.typed[-1]}\n", "❯\u00a0\n")
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
        for words in (["claude"], ["claude", "-p"], ["claude", "--print"],
                      ["node", "/fake/node_modules/@anthropic-ai/claude-code/cli.js"]):
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
        with patch.object(orch, "tmux_out", return_value=(0, "/fake/agentkit-test\tother\t101\t%7")):
            self.hook()
        self.assertEqual(self.record(), before)

    def test_renamed_seat_and_named_login_follow_repeated_clears(self):
        orch.rename("lagoon", "quay")
        config.update_session("quay", account="second")
        self.title("after-clear", "quay")
        self.hook()
        self.title("next-clear", "quay")
        self.hook(conversation="next-clear")
        self.assertEqual(self.record()["conversation"], "next-clear")
        self.assertEqual(self.record()["account"], "second")
        self.assertEqual(config.resolve_session("lagoon"), "quay")
        self.assertEqual(claude.session_title(self.record()), "quay")
        self.assertFalse(claude.transcript_path({**self.record(), "account": "default"},
                                               "next-clear").exists())
        self.assert_resume("next-clear")

    def test_named_login_with_the_adapters_projects_link_follows_clear(self):
        config.update_session("lagoon", account="second")
        # Command preparation makes the normal shared store; no Claude process is started.
        orch.command(self.cfg, "opus", "before-clear", account="second")
        projects = self.root / ".claude-second/projects"
        self.assertTrue(projects.is_symlink())
        self.assertEqual(projects.resolve(), self.root / ".claude/projects")
        self.hook()
        self.title("after-clear", "Checkout Bug")
        self.assertEqual(self.record()["conversation"], "after-clear")
        self.assertEqual(claude.session_title(self.record()), "Checkout Bug")
        self.assert_resume("after-clear")

    def test_second_window_and_split_pane_cannot_claim_the_conversation(self):
        before = self.record()
        for pane, root in (("%8", 201), ("%9", 301)):
            with self.subTest(pane=pane), patch.dict(os.environ, {"TMUX_PANE": pane}):
                self.table.update({root: (1, ["bash"]), root + 1: (root, ["claude"]),
                                   root + 2: (root + 1, ["sh", "-c", "hook"])})
                self.hook(pid=root + 2)
                self.assertEqual(self.record(), before)
        self.hook()
        self.assertEqual(self.record()["conversation"], "after-clear")

    def test_a_pane_without_launch_evidence_cannot_claim_the_conversation(self):
        self.bound_pane = ""
        before = self.record()
        self.hook()
        self.assertEqual(self.record(), before)

    def tick(self, dry=False):
        watch.health(self.cfg, watch.load_state(), dry, lambda _: None)

    def test_running_seat_binds_its_client_once_then_follows_clear(self):
        self.bound_pane, self.active_pane = "", "%8"
        self.table.update({201: (1, ["bash"]), 301: (1, ["claude", "--resume", "other"]),
                           302: (301, ["claude", "--resume", "before-clear"])})
        for words in (["claude", "--session-id", "before-clear"],
                      ["claude", "--resume", "before-clear"],
                      ["node", "/fake/node_modules/@anthropic-ai/claude-code/cli.js",
                       "--session-id", "before-clear"]):
            with self.subTest(words=words):
                self.bound_pane = ""
                config.update_session("lagoon", conversation="before-clear")
                self.table[102] = (101, words)
                self.tmux_calls.clear()
                self.tick()
                self.assertEqual(self.bound_pane, "%7")
                self.hook()
                self.assertEqual(self.record()["conversation"], "after-clear")
                self.tick()
                bindings = [args for args in self.tmux_calls
                            if args[0] == "set-option" and orch.PANE_OPTION in args]
                self.assertEqual(len(bindings), 1)
                self.assertFalse(any("respawn-pane" in args or "new-session" in args
                                     for args in self.tmux_calls))

    def test_wrapper_keeps_launch_evidence_when_client_arguments_are_missing(self):
        self.bound_pane = ""
        self.table[101][1].extend(["--session-id", "before-clear"])
        self.table[102] = (101, ["claude"])
        self.tick()
        self.assertEqual(self.bound_pane, "%7")
        self.hook()
        self.assertEqual(self.record()["conversation"], "after-clear")

    def test_direct_client_binds_but_dead_or_ambiguous_panes_do_not(self):
        self.bound_pane = ""
        self.panes = {"%7": (102, True)}
        self.tick()
        self.assertEqual(self.bound_pane, "")
        self.panes["%7"] = (102, False)
        self.panes["%8"] = (201, False)
        self.table[201] = (1, ["claude", "--resume", "before-clear"])
        self.tick()
        self.assertEqual(self.bound_pane, "")
        del self.panes["%8"]
        self.tick()
        self.assertEqual(self.bound_pane, "%7")
        self.hook()
        self.assertEqual(self.record()["conversation"], "after-clear")

    def test_shell_nested_worker_and_unrelated_clients_cannot_bind(self):
        before = self.record()
        self.panes = {"%8": (201, False)}
        self.active_pane = "%8"
        for table in ({201: (1, ["bash"])},
                      {201: (1, ["bash"]), 202: (201, ["claude", "--resume", "before-clear"])},
                      {201: (1, ["claude"]), 202: (201, ["claude", "--resume", "before-clear"])},
                      {201: (1, ["claude", "--print", "--resume", "before-clear"])},
                      {201: (1, ["claude", "--resume", "other"])},
                      {201: (1, ["python3", "other.py", "--resume", "before-clear"])},
                      {}):
            with self.subTest(table=table):
                self.table, self.bound_pane = table, ""
                self.tick()
                self.assertEqual(self.bound_pane, "")
                self.assertEqual(self.record(), before)

    def test_dry_run_exited_and_other_harness_seats_are_not_bound(self):
        self.bound_pane = ""
        self.tick(dry=True)
        self.assertEqual(self.bound_pane, "")
        self.seat["exited"] = True
        self.tick()
        self.assertEqual(self.bound_pane, "")
        self.seat["exited"] = False
        config.update_session("lagoon", orchestrator="astra")
        self.tick()
        self.assertEqual(self.bound_pane, "")

    def test_show_options_needs_a_real_tmux_target(self):
        self.assertEqual(self.tmux("show-options", "-qv", "-t", "=lagoon", orch.PANE_OPTION),
                         (0, ""))
        self.assertEqual(self.tmux("show-options", "-qv", "-t", "=lagoon:", orch.PANE_OPTION),
                         (0, "%7"))

    def test_launch_binds_the_pane_and_respawn_keeps_it_when_another_pane_is_active(self):
        self.bound_pane = ""
        orch.start("lagoon", self.root, ["claude"], "opus")
        self.assertEqual(self.bound_pane, "%7")
        self.active_pane = "%8"
        with patch.dict(os.environ, {"TMUX_PANE": "%8"}):
            orch.launch("lagoon", "opus", self.root, ["claude"], "before-clear", self.seat)
        respawn = next(args for args in self.tmux_calls if args[0] == "respawn-pane")
        self.assertEqual(respawn[respawn.index("-t") + 1], "%7")
        self.assertEqual(self.bound_pane, "%7")

    def test_resume_with_gone_pane_uses_and_records_the_sessions_pane(self):
        self.panes = {"%8": (201, False)}
        self.active_pane = "%8"
        self.table = {201: (1, ["bash"])}
        for exited in (False, True):
            with self.subTest(exited=exited):
                self.seat["exited"], self.bound_pane = exited, "%7"
                self.tmux_calls.clear()
                # Changing login can restart a live session whose only remaining pane is a shell.
                self.assertEqual(orch.resume(self.cfg, "lagoon", hand_over=False,
                                             account=None if exited else "default",
                                             log=lambda _: None), "resumed")
                respawn = next(args for args in self.tmux_calls if args[0] == "respawn-pane")
                self.assertEqual(respawn[respawn.index("-t") + 1], "=lagoon:")
                self.assertIn("--resume before-clear", respawn[-1])
                self.assertEqual(self.bound_pane, "%8")

    def test_fresh_server_launch_without_stdout_still_follows_clear(self):
        self.server_up, self.bound_pane = False, ""
        with patch.object(orch, "tmux_out", side_effect=self.tmux) as tmux:
            orch.start("lagoon", self.root, ["claude"], "opus")
        launch = next(call for call in tmux.call_args_list if "new-session" in call.args)
        self.assertEqual(launch.kwargs["unit"], "agentkit-seat-lagoon")
        self.assertEqual(self.bound_pane, "%7")
        self.hook()
        self.assertEqual(self.record()["conversation"], "after-clear")

    def test_other_harnesses_take_no_notify_lock(self):
        for model in ("astra", "spark"):
            with self.subTest(model=model):
                config.update_session("lagoon", orchestrator=model)
                before = self.record()
                with patch.object(notify, "session_lock", side_effect=AssertionError("would block")):
                    self.hook()
                self.assertEqual(self.record(), before)

    def test_in_session_resume_and_its_later_events_do_not_claim_another_seats_transcript(self):
        config.save_session(self.cfg, "quay", "opus", ["opus"], {
            "cwd": str(self.root), "conversation": "after-clear", "id_source": orch.LAUNCHER})
        before = config.session_records()
        for event in ("SessionStart", "UserPromptSubmit", "Stop", "Notification"):
            with self.subTest(event=event):
                self.hook(hook_event_name=event, source="resume")
                self.assertEqual(config.session_records(), before)

    def test_npm_claude_can_follow_clear_but_another_cli_script_cannot(self):
        self.table[102] = (101, ["node", "/fake/other/cli.js"])
        before = self.record()
        self.hook()
        self.assertEqual(self.record(), before)
        self.table[102] = (101, ["node", "--no-warnings", "--",
                                "/fake/node_modules/@anthropic-ai/claude-code/cli.js"])
        self.hook()
        self.assertEqual(self.record()["conversation"], "after-clear")

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
  display-message) printf '/fake/agentkit-test\\tlagoon\\t101\\t%%7\\n' ;;
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
