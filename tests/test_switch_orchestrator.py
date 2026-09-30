"""An open session moves to another orchestrator from the menu, its runs untouched.

Picking another model in the `c` screen's orchestrator column moves the seat to it at
once under the same name: the old harness process ends, the new one starts in the seat's
directory, and the runs, plan file and record stay, with the new orchestrator in the
record. The handover -- from which model, the plan file, `ak run status`, and the old
transcript to read the last exchange from -- is marked for the tick, which types it
after the new TUI is listening through the confirmed send. A model whose harness is not
installed or not logged in, or whose meter is spent, is refused in one line with the
seat as it was, as is a restart that fails.

Offline: a temporary HOME, fake harness adapters and binaries, a fake tmux, and no real
process signalled. The seat listing is faked live or gone; the session records, plan
file and run receipts are real files in the throwaway HOME.
"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from test_v4n import Sandbox
from agentkit import config, menu, orch, run, terminal, watch
from agentkit.harness import codex as codex_plugin

CONVERSATION = "d6fae368-678c-444e-8032-9c5c5338c84e"

ADAPTER = r'''#!/usr/bin/env bash
set -uo pipefail
H="__H__"
STATE="__STATE__"
case "${1:-}" in
interactive)
  if [ "${5:-}" = new ]; then
    case "$H" in codex|muse|opencode|antigravity)
      echo "$H.sh interactive: the TUI cannot be given a session id" >&2; exit 3 ;;
    esac
  fi
  echo "fake-tui-$H $2 $3 ${4:-} ${5:-}" ;;
auth)
  if [ -s "$STATE/logged-out-$H" ] || [ -s "$STATE/logged-out" ]; then
    echo "$H: not logged in; run login" >&2; exit 1
  fi
  echo "$H: the token is still valid" ;;
*) echo "fake adapter: no ${1:-}" >&2; exit 2 ;;
esac
'''

BINARIES = {"claude": "claude", "codex": "codex", "muse": "muse",
            "grokbuild": "grok", "opencode": "opencode", "antigravity": "agy"}


class Switch(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AGENTKIT_SESSION": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.fixture = self.root / "fixture"
        self.fixture.mkdir()
        self.adapters = self.root / "adapters"
        self.adapters.mkdir()
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            path = self.adapters / f"{harness}.sh"
            path.write_text(ADAPTER.replace("__STATE__", str(self.fixture)).replace(
                "__H__", harness))
            path.chmod(0o755)
        self.stack.enter_context(patch.dict(
            os.environ, {config.ADAPTER_DIR_ENV: str(self.adapters)}))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for harness, program in BINARIES.items():
            path = self.bin / program
            path.write_text("#!/bin/sh\nexit 0\n")
            path.chmod(0o755)
        self.stack.enter_context(patch.dict(
            os.environ, {"PATH": f"{self.bin}:{os.environ['PATH']}"}))
        self.calls, self.fail = [], set()
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.seat = {"name": "fix-api", "path": str(self.root), "created": 100,
                     "attached": False, "exited": False, "legacy": False}
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[self.seat]))
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"],
                            {"reviewers": ["astra"], "cwd": str(self.root),
                             "created": 100, "conversation": CONVERSATION,
                             "id_source": orch.LAUNCHER})
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.root))
        transcript = Path(os.environ["HOME"]) / ".claude/projects" / slug \
            / f"{CONVERSATION}.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text('{"type":"user","text":"what changed?"}\n'
                              '{"type":"assistant","text":"the endpoint"}\n')
        self.transcript = str(transcript)
        config.plan_path("fix-api").write_text("- [ ] Finish the endpoint\n")
        going = config.RUNS / "going"
        going.mkdir()
        run.save_state(going, {"run_id": "going", "state": "running",
                               "launched_session": "fix-api"})
        ended = config.RUNS / "ended"
        ended.mkdir()
        run.save_state(ended, {"run_id": "ended", "state": "pass", "verdict": "PASS",
                               "launched_session": "fix-api", "reported": False,
                               "finished_at": 9990})

    def tmux(self, *args, **kwargs):
        self.calls.append(args)
        if args[0] in self.fail:
            return 1, "boom"
        return 0, ""

    def selected(self, name="fix-api"):
        record = config.load_session(self.cfg, name)
        found = {"orchestrator": record["orchestrator"], "workers": list(record["workers"])}
        if "reviewers" in record:
            found["reviewers"] = list(record["reviewers"])
        return found

    def test_switch_moves_the_seat_at_once_and_keeps_runs_plan_and_record(self):
        before = config.load_session(self.cfg, "fix-api")
        plan = config.plan_path("fix-api").read_bytes()
        going = run.read_state(config.RUNS / "going")
        ended = run.read_state(config.RUNS / "ended")
        state = watch.load_state()
        state["stalls"]["fix-api"] = {"status": "waiting"}
        watch.save_state(state)
        selected = self.selected()
        with patch.object(run, "stop_owned_runs",
                          side_effect=AssertionError("runs are never stopped")):
            self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "astra", 0, {}),
                             "")
        self.assertEqual(selected["orchestrator"], "astra")
        after = config.load_session(self.cfg, "fix-api")
        self.assertEqual(after["orchestrator"], "astra")
        for key in ("workers", "reviewers", "cwd", "created"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(config.plan_path("fix-api").read_bytes(), plan)
        self.assertEqual(run.read_state(config.RUNS / "going"), going)
        self.assertEqual(run.read_state(config.RUNS / "ended"), ended)
        self.assertNotIn("fix-api", watch.load_state()["stalls"])
        respawns = [args for args in self.calls if args[0] == "respawn-pane"]
        self.assertEqual(len(respawns), 1)
        self.assertIn("-k", respawns[0])           # the old harness process ends
        self.assertIn("fake-tui-codex", respawns[0][-1])
        self.assertEqual([args for args in self.calls if args[0] == "kill-session"], [])
        # nothing typed yet: the new TUI is still starting, and the tick says it
        self.assertEqual([args for args in self.calls if args[0] == "send-keys"], [])
        mark = watch.seat_read("fix-api").get("midturn")
        self.assertEqual((mark["boot"], mark["name"]), (watch.boot_id(), "fix-api"))
        for part in ("opus", str(config.plan_path("fix-api")), "ak run status",
                     self.transcript, "read the last exchange"):
            self.assertIn(part, mark["line"])

    def test_the_tick_types_the_handover_after_the_warmup(self):
        selected = self.selected()
        self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "astra", 0, {}),
                         "")
        line = watch.seat_read("fix-api")["midturn"]["line"]
        self.calls.clear()
        sleeps, logs = [], []
        with patch.object(watch.time, "sleep", side_effect=sleeps.append), \
                patch.object(watch, "look_at", return_value=("codex", {})):
            watch.continue_turns(self.cfg, logs.append)
        self.assertTrue(any(sleep > 9 for sleep in sleeps), sleeps)   # INBOX_WARMUP first
        self.assertIn(watch.KEY_GAP, sleeps)         # ... text and Enter go separately
        sent = [args for args in self.calls if args[0] == "send-keys"]
        self.assertEqual([args[1:] for args in sent],
                         [("-t", "=fix-api:", "-l", line), ("-t", "=fix-api:", "Enter")])
        self.assertIsNone(watch.seat_read("fix-api").get("midturn"))
        self.assertTrue(any("continue" in entry for entry in logs), logs)

    def test_a_seat_tmux_lost_starts_again_in_its_directory(self):
        with patch.object(orch, "sessions", return_value=[]):
            selected = self.selected()
            self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "astra", 0,
                                               {}), "")
        self.assertEqual(config.load_session(self.cfg, "fix-api")["orchestrator"], "astra")
        started = [args for args in self.calls if "new-session" in args]
        self.assertEqual(len(started), 1)
        at = started[0].index("-c")
        self.assertEqual(started[0][at + 1], str(self.root))
        self.assertIn("fake-tui-codex", started[0][-1])
        self.assertEqual(config.plan_path("fix-api").read_text(),
                         "- [ ] Finish the endpoint\n")
        self.assertEqual([args for args in self.calls if args[0] == "send-keys"], [])
        self.assertIn("ak run status",
                      watch.seat_read("fix-api")["midturn"]["line"])

    def test_a_restart_that_fails_says_so_in_one_line_and_keeps_the_record(self):
        before = config.load_session(self.cfg, "fix-api")
        self.fail.add("respawn-pane")
        note = menu.session_mark(self.cfg, "fix-api", self.selected(), "astra", 0, {})
        self.assertTrue(note)
        self.assertNotIn("\n", note)
        self.assertEqual(config.load_session(self.cfg, "fix-api"), before)
        self.assertEqual(list(config.STATE.glob("codex-launch-*.json")), [])
        self.assertIsNone(watch.seat_read("fix-api").get("midturn"))
        self.fail.clear()
        with patch.object(orch, "fresh_command",
                          side_effect=config.Error("adapter boom\nsecond line")):
            note = menu.session_mark(self.cfg, "fix-api", self.selected(), "astra", 0, {})
        self.assertEqual(note, "adapter boom second line")
        self.assertEqual(config.load_session(self.cfg, "fix-api"), before)

    def test_the_handover_names_takeover_plan_status_and_transcript(self):
        text = orch.handover_text("fix-api", "opus", self.transcript)
        self.assertIn("opus", text)
        self.assertIn(str(config.plan_path("fix-api")), text)
        self.assertIn("ak run status", text)
        self.assertIn(self.transcript, text)
        self.assertIn("read the last exchange", text)
        text = orch.handover_text("fix-api", "spark", None)
        self.assertIn("spark", text)
        self.assertIn("no transcript file", text)
        self.assertIn("ak run status", text)

    def test_a_harness_not_installed_logged_out_or_spent_is_refused_in_one_line(self):
        selected = self.selected()
        before = config.load_session(self.cfg, "fix-api")
        with patch.object(config, "harness_binary", return_value=""):
            refused = [menu.session_mark(self.cfg, "fix-api", selected, "astra", 0, {})]
        self.assertIn("not installed", refused[0])
        (self.fixture / "logged-out-codex").write_text("yes\n")
        refused.append(menu.session_mark(self.cfg, "fix-api", selected, "astra", 0, {}))
        self.assertIn("not logged in", refused[1])
        (self.fixture / "logged-out-codex").unlink()
        spent = {"openai": {"meters": [{"name": "weekly_all", "used": 100,
                                        "resets_at": time.time() + 86400,
                                        "window_secs": 604800}]}}
        refused.append(menu.session_mark(self.cfg, "fix-api", selected, "astra", 0, spent))
        self.assertIn("spent", refused[2])
        for note in refused:
            self.assertTrue(note)
            self.assertNotIn("\n", note)
        self.assertEqual(selected["orchestrator"], "opus")
        self.assertEqual(config.load_session(self.cfg, "fix-api"), before)
        self.assertEqual([args for args in self.calls
                          if args[0] in ("respawn-pane", "new-session", "send-keys")], [])
        self.assertIsNone(watch.seat_read("fix-api").get("midturn"))
        self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "opus", 0, {}), "")
        self.assertEqual(self.calls, [])

    def test_runs_that_end_later_report_to_the_new_seat(self):
        selected = self.selected()
        self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "astra", 0, {}),
                         "")
        run_dir = config.RUNS / "going"
        state = run.read_state(run_dir)
        run.save_state(run_dir, {**state, "state": "pass", "verdict": "PASS",
                                 "finished_at": 10000})
        told = []
        with patch.object(watch, "type_at_prompt",
                          side_effect=lambda seat, line, *a, **k: told.append(
                              (seat["name"], line)) or True):
            run.announce(run.read_state(run_dir), run_dir, lambda _: None, cfg=self.cfg)
        self.assertEqual(len(told), 1)
        self.assertEqual(told[0][0], "fix-api")
        self.assertIn("going", told[0][1])
        self.assertEqual(config.load_session(self.cfg, "fix-api")["orchestrator"], "astra")
        self.assertTrue(run.read_state(run_dir)["handed_back"])

    def test_a_codex_seat_moved_on_drops_its_launch_receipt(self):
        path = self.fixture / "rollout.jsonl"
        path.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": "thread", "cwd": str(self.root)}}) + "\n")
        config.save_session(self.cfg, "codex-seat", "astra", ["opus"],
                            {"cwd": str(self.root), "created": 100})
        receipt = codex_plugin.prepare("codex-seat", self.root, None)
        codex_plugin.capture(receipt, {"hook_event_name": "SessionStart", "source": "startup",
                                       "session_id": "thread", "transcript_path": str(path),
                                       "cwd": str(self.root)})
        record = config.session_records()["codex-seat"]
        self.assertTrue(codex_plugin.path_for(record).exists())
        seat = dict(self.seat, name="codex-seat")
        with patch.object(orch, "sessions", return_value=[seat]):
            selected = self.selected("codex-seat")
            self.assertEqual(menu.session_mark(self.cfg, "codex-seat", selected, "opus", 0,
                                               {}), "")
        self.assertEqual(config.load_session(self.cfg, "codex-seat")["orchestrator"], "opus")
        self.assertFalse(codex_plugin.path_for(record).exists())

    def test_each_harness_says_where_its_transcript_is(self):
        record = config.load_session(self.cfg, "fix-api")
        from agentkit.harness import load as plugin
        self.assertEqual(plugin("claude").transcript(record, str(self.root), CONVERSATION),
                         self.transcript)
        Path(self.transcript).unlink()
        self.assertIsNone(plugin("claude").transcript(record, str(self.root), CONVERSATION))
        self.assertIsNone(plugin("claude").transcript(record, str(self.root), None))
        path = self.fixture / "rollout.jsonl"
        path.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": "thread", "cwd": str(self.root)}}) + "\n")
        config.save_session(self.cfg, "codex-seat", "astra", ["opus"],
                            {"cwd": str(self.root), "created": 100})
        receipt = codex_plugin.prepare("codex-seat", self.root, None)
        codex_plugin.capture(receipt, {"hook_event_name": "SessionStart", "source": "startup",
                                       "session_id": "thread", "transcript_path": str(path),
                                       "cwd": str(self.root)})
        stored = config.session_records()["codex-seat"]
        self.assertEqual(plugin("codex").transcript(stored, str(self.root), "thread"),
                         str(path))
        self.assertIsNone(plugin("codex").transcript(stored, str(self.root), None))
        grok = {"orchestrator": "grok", "cwd": str(self.root)}
        self.assertIsNone(plugin("grokbuild").transcript(grok, str(self.root), CONVERSATION))
        from agentkit.harness import grokbuild
        history = grokbuild.session_dir(str(self.root), CONVERSATION) / "chat_history.jsonl"
        history.parent.mkdir(parents=True)
        history.write_text("{}\n")
        self.assertEqual(plugin("grokbuild").transcript(grok, str(self.root), CONVERSATION),
                         str(history))
        self.assertIsNone(plugin("muse").transcript({}, None, None))
        self.assertIsNone(plugin("opencode").transcript({}, None, None))

    def test_the_config_screen_holds_the_orchestrator_and_a_dry_run_draws_it(self):
        with patch.object(terminal, "layout_width", return_value=100):
            lines, _ = menu.config_body(self.cfg, "fixture", ("model", "opus"), 0,
                                        self.selected())
        self.assertEqual(lines[0].split(), ["orch", "exec", "review", "effort"])
        rows = {terminal.plain(line).lstrip("› ").split()[0]: "".join(
            char for char in terminal.plain(line) if char in "●○■□") for line in lines
                if any(char in terminal.plain(line) for char in "●○■□")}
        self.assertEqual(rows["opus"], "●■□")
        self.assertEqual(rows["astra"], "○■■")
        with patch.object(menu.update, "agentkit_version", return_value="fixture"), \
                patch.object(menu.usage, "collect", return_value={}), \
                patch.object(terminal, "layout_width", return_value=100), \
                redirect_stdout(io.StringIO()) as out:
            menu.show_config(dry_run=True, session="fix-api")
        screen = out.getvalue()
        self.assertIn("agentkit · config · fix-api", screen)
        self.assertIn("orch", screen)
        self.assertIn("exec", screen)
        self.assertIn("review", screen)
        with patch.object(terminal, "layout_width", return_value=40):
            lines, _ = menu.config_body(self.cfg, "fixture", selected=self.selected())
        self.assertTrue(all(terminal.cells(line) <= 40 for line in lines))


if __name__ == "__main__":
    unittest.main(verbosity=2)
