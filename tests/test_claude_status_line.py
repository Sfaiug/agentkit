"""Status-line composition, conversation reports and their collection, with a temporary HOME."""

from datetime import datetime, timezone
from functools import partial
import json
import os
import shlex
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, gc, usage, watch
from agentkit.harness import claude


class ClaudeStatusLine(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(config, "STATE", self.root / ".agentkit/state"))
        config.STATE.mkdir(parents=True)
        self.cwd = self.root / "acme"
        self.cwd.mkdir()
        self.env = {**os.environ, "AGENTKIT_SESSION": "acme", "AK_RUN_ROLE": "",
                    "AGENTKIT_RULEBOOK": str(self.root / "rules"), "AGENTKIT_ACCOUNT": "",
                    "TMUX": "", "TMUX_PANE": "", "AGENTKIT_CLAUDE_CHECKED": "1"}
        self.env.pop("CLAUDE_CONFIG_DIR", None)
        self.payload = '{"session_id":"conv-acme","model":{"id":"claude-sonnet-5-5"}}\n\n'
        self.report = config.STATE / "model-conv-acme.json"

    def run_command(self, command, **env):
        done = subprocess.run(["bash", "-c", command], input=self.payload, text=True,
                              capture_output=True, cwd=self.cwd, env={**self.env, **env}, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_launch_preserves_the_first_status_line_and_the_shell_runs_it_verbatim(self):
        files = [self.cwd / ".claude/settings.local.json", self.cwd / ".claude/settings.json",
                 self.root / ".claude/settings.json"]
        for index, file in enumerate(files):
            file.parent.mkdir(parents=True, exist_ok=True)
            owner = f"read -r payload\ncat <<EOF\n{index}\nEOF\n# owner's comment"
            file.write_text(json.dumps({"statusLine": {"type": "command", "command": owner,
                                                      "padding": index}}))
        for index, file in enumerate([*files, None]):
            done = subprocess.run([str(REPO / "adapters/claude.sh"), "interactive", "opus", "high"],
                                  capture_output=True, text=True, cwd=self.cwd, env=self.env, timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr)
            words = shlex.split(done.stdout)
            status = json.loads(words[words.index("--settings") + 1])["statusLine"]
            if file is None:
                self.assertEqual(self.run_command(status["command"]), "")
                break
            self.assertEqual(status["padding"], index)
            self.assertEqual(self.run_command(status["command"]), f"{index}\n")
            file.unlink()

    def test_reports_change_only_with_the_values_and_workers_pass_through_without_writing(self):
        command = shlex.quote(str(REPO / "hooks/claude-status.sh"))
        self.assertEqual(self.run_command(command, AK_RUN_ROLE="worker"), self.payload)
        self.assertFalse(self.report.exists())
        self.assertEqual(self.run_command(command, AGENTKIT_SESSION=""), self.payload)
        self.assertFalse(self.report.exists())
        self.assertEqual(self.run_command(command), self.payload)
        self.assertEqual(json.loads(self.report.read_text()), {"model": "claude-sonnet-5-5", "effort": None})
        os.utime(self.report, (1000, 1000))
        self.run_command(command)
        self.assertEqual(self.report.stat().st_mtime, 1000)
        self.report.unlink()
        self.assertEqual(self.run_command(command + " | { printf owner; }"), "owner")
        self.assertTrue(self.report.exists())

    def test_a_replaced_report_keeps_its_own_timestamp(self):
        self.run_command(shlex.quote(str(REPO / "hooks/claude-status.sh")))
        os.utime(self.report, (1000, 1000))
        load = json.load

        def replacing(stream):
            report = load(stream)
            other = self.report.with_suffix(".next")
            other.write_text('{"model":"claude-opus-5-5","effort":"max"}')
            os.utime(other, (4000, 4000))
            other.replace(self.report)
            return report

        with patch.object(claude.json, "load", side_effect=replacing):
            self.assertEqual(claude.running({}, None, "conv-acme"), ("claude-sonnet-5-5", None, 1000))

    def test_running_uses_the_newer_answer_or_report_and_only_that_conversation(self):
        self.run_command(shlex.quote(str(REPO / "hooks/claude-status.sh")))
        os.utime(self.report, (1000, 1000))
        record = {"cwd": str(self.cwd)}
        self.assertEqual(claude.running(record, self.cwd, "conv-acme"), ("claude-sonnet-5-5", None, 1000))
        self.assertIsNone(claude.running(record, self.cwd, "conv-other"))
        path = claude.transcript_path(record, "conv-acme")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"type": "assistant", "message": {"model": "claude-opus-5-5"},
            "effort": "max", "timestamp": datetime.fromtimestamp(2000, timezone.utc).isoformat()}))
        self.assertEqual(claude.running(record, self.cwd, "conv-acme"), ("claude-opus-5-5", "max", 2000))
        os.utime(self.report, (3000, 3000))
        self.assertEqual(claude.running(record, self.cwd, "conv-acme"), ("claude-sonnet-5-5", None, 3000))
        config.save_session(self.cfg, "renamed", "opus", ["astra"], {"conversation": "conv-acme"})
        self.assertEqual(list(gc.stale_model_reports()), [])
        config.update_session("renamed", conversation="conv-new")
        self.assertEqual([item["path"] for item in gc.stale_model_reports()], [str(self.report)])
        with patch.object(gc, "gc_candidates", side_effect=gc.stale_model_reports), \
                patch.object(gc.jobs, "forget_owner_words"):
            self.assertEqual(gc.gc(lambda _: None), [str(self.report)])
        self.assertFalse(self.report.exists())

    def render(self, limits, shell='. "$0"', **env):
        """The hook run in `shell` on a render carrying `limits`, waited out with all it started."""
        end, held = os.pipe()
        self.addCleanup(os.close, end)
        subprocess.run(["bash", "-c", shell, REPO / "hooks/claude-status.sh"], env={**self.env, **env},
                       input=json.dumps({**json.loads(self.payload), "rate_limits": limits}),
                       text=True, capture_output=True, timeout=30, pass_fds=(held,))
        os.close(held)
        self.assertEqual(os.read(end, 1), b"")

    def test_renders_are_judged_in_the_order_they_were_rendered(self):
        config.save_session(self.cfg, "acme", "opus", ["opus"], {"conversation": "conv-acme"})
        hand_in = partial(watch.hook_meters, "acme", "conv-acme", "")
        hand_in("1000", "five_hour 20 30000", "seven_day 20 900000")
        # a later render's hand-in arrives before an earlier one's; then a worker's turn, at 10000
        hand_in("3000", "seven_day 40 900000")
        hand_in("2000", "five_hour 30 30000", "seven_day 20 900000")
        usage.record_turn_meters(self.cfg, "anthropic", [{"name": "session", "used": 50}])
        note = (config.STATE / "limits-conv-acme.json").read_text()
        limits = {"five_hour": {"used_percentage": 30, "resets_at": 30000},
                  "seven_day": {"used_percentage": 40, "resets_at": 900000}}
        self.render(limits)
        self.assertEqual((config.STATE / "limits-conv-acme.json").read_text(), note)
        self.assertEqual({meter["name"]: meter["used"]
                          for meter in usage._cached_provider("anthropic")["meters"]},
                         {"session": 50, "weekly_all": 40})

    def test_a_bash_without_a_clock_hands_in_no_limits(self):
        config.save_session(self.cfg, "acme", "opus", ["opus"], {"conversation": "conv-acme"})
        watch.hook_meters("acme", "conv-acme", "", "1000", "seven_day 20 900000")
        watch.hook_meters("acme", "conv-acme", "", "2000", "seven_day 30 900000")
        note = config.STATE / "limits-conv-acme.json"
        held = note.read_text(), usage._cached_provider("anthropic")
        self.render({"seven_day": {"used_percentage": 40, "resets_at": 900000}},
                    'unset EPOCHREALTIME; . "$0"')
        self.assertEqual((note.read_text(), usage._cached_provider("anthropic")), held)
        self.assertEqual([meter["used"] for meter in held[1]["meters"]], [30])


if __name__ == "__main__":
    unittest.main()
