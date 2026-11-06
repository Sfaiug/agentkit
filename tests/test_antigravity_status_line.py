"""agy's own status command survives composition; only a newer report wins over an answer."""

import contextlib
import json
import os
import shlex
import sqlite3
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, gc
from agentkit.harness import antigravity
from test_key_model_followed_antigravity import TABLES, nested, stamp


class AntigravityStatusLine(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(config, "STATE", self.root / ".agentkit/state"))
        config.STATE.mkdir(parents=True)
        rules = self.root / "rules.md"
        rules.write_text("acme's rules\n")
        self.env = {**os.environ, "AGENTKIT_SESSION": "acme", "AK_RUN_ROLE": "",
                    "AGENTKIT_RULEBOOK": str(rules), "AGENTKIT_ACCOUNT": "",
                    "TMUX": "", "TMUX_PANE": ""}
        self.payload = {"session_id": "conv-acme", "conversation_id": "conv-acme",
                        "model": {"id": "Gemini 4 Argon (Low)",
                                  "display_name": "Gemini 4 Argon (Low)", "effort": "low"}}
        self.report = config.STATE / "model-conv-acme.json"

    def launch(self, account=""):
        done = subprocess.run([str(REPO / "adapters/antigravity.sh"), "interactive",
                               "gemini-3.8-flash", "high"], capture_output=True, text=True,
                              cwd=self.root, env={**self.env, "AGENTKIT_ACCOUNT": account}, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        words = shlex.split(done.stdout)
        return json.loads(words[words.index("--settings") + 1])["statusLine"]

    def render(self, status, **env):
        done = subprocess.run(["sh", "-c", status["command"]], input=json.dumps(self.payload),
                              text=True, capture_output=True, cwd=self.root,
                              env={**self.env, **env}, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_composition_reads_only_that_accounts_settings_and_preserves_the_command(self):
        self.assertEqual(self.render(self.launch()), "")
        settings = self.root / ".gemini/antigravity-cli/settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        owner = "read -r payload\ncat <<EOF\nusual\nEOF\n# owner's comment"
        original = json.dumps({"statusLine": {"type": "command", "command": owner, "padding": 4}})
        settings.write_text(original)
        status = self.launch()
        self.assertEqual(status["padding"], 4)
        self.assertEqual(self.render(status), "usual\n")
        self.assertEqual(self.render(self.launch("acme")), "")
        own = self.root / ".gemini/antigravity-cli-acme/settings.json"
        own.write_text(json.dumps({"statusLine": {"type": "command", "command": "printf named"}}))
        self.assertEqual(self.render(self.launch("acme")), "named")
        self.assertEqual(settings.read_text(), original)
        settings.write_text("malformed")
        self.assertEqual(self.render(self.launch()), "")

    def test_empty_conversations_and_workers_write_nothing_and_identical_renders_keep_the_date(self):
        status = self.launch()
        self.payload.update(session_id="", conversation_id="")
        self.assertEqual(self.render(status), "")
        self.assertEqual(list(config.STATE.glob("model-*.json")), [])
        self.payload.update(session_id="conv-acme", conversation_id="conv-acme")
        self.render(status, AK_RUN_ROLE="worker")
        self.assertFalse(self.report.exists())
        self.render(status)
        self.assertEqual(json.loads(self.report.read_text()),
                         {"model": "Gemini 4 Argon (Low)", "effort": "low"})
        os.utime(self.report, (1000, 1000))
        self.render(status)
        self.assertEqual(self.report.stat().st_mtime, 1000)

    def test_running_uses_the_newer_answer_or_report_and_only_that_conversation(self):
        self.render(self.launch())
        os.utime(self.report, (1000, 1000))
        self.assertEqual(antigravity.running({}, None, "conv-acme"), ("gemini-4-argon", "low", 1000))
        self.assertIsNone(antigravity.running({}, None, "conv-other"))
        self.assertIsNone(antigravity.running({}, None, ""))
        path = antigravity.store("conv-acme")
        path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(sqlite3.connect(path)) as db, db:
            for table in TABLES:
                db.execute(table)
            db.execute("INSERT INTO steps (idx, step_type, metadata) VALUES (0, 15, ?)",
                       (stamp(8, 2000) + nested(12, b"run"),))
            db.execute("INSERT INTO gen_metadata (idx, data) VALUES (0, ?)",
                       (nested(3, nested(28, b"gemini-3.8-flash-high")) + nested(4, b"run"),))
        self.assertEqual(antigravity.running({}, None, "conv-acme"), ("gemini-3.8-flash", "high", 2000))
        os.utime(self.report, (3000, 3000))
        self.assertEqual(antigravity.running({}, None, "conv-acme"), ("gemini-4-argon", "low", 3000))
        for invalid in ("[]", "malformed"):
            self.report.write_text(invalid)
            self.assertEqual(antigravity.running({}, None, "conv-acme"),
                             ("gemini-3.8-flash", "high", 2000))

    def test_catalog_labels_translate_for_other_models_too(self):
        status = self.launch()
        for label, model, effort in (("GPT-OSS 120B (Medium)", "gpt-oss-120b", "medium"),
                                     ("Claude Sonnet 5.5 (High)", "claude-sonnet-5-5", "high")):
            self.payload["model"] = {"id": label, "display_name": label, "effort": effort}
            self.render(status)
            self.assertEqual(antigravity.running({}, None, "conv-acme")[:2], (model, effort))

    def test_gc_keeps_a_learned_conversations_report_until_the_next_launch(self):
        config.save_session(self.cfg, "acme", "gemini", ["gemini"])
        token = antigravity.launched("acme", self.root, None)[antigravity.LAUNCH_ENV]
        proc = self.root / "proc"
        fd = proc / "123/fd"
        fd.mkdir(parents=True)
        (fd.parent / "environ").write_bytes(f"{antigravity.LAUNCH_ENV}={token}\0".encode())
        (fd / "0").symlink_to(antigravity.store("conv-acme"))
        with patch.object(antigravity, "PROC", proc):
            self.assertEqual(antigravity.conversation(config.session_record("acme")), "conv-acme")
            self.assertIsNone(config.session_record("acme").get("conversation"))
            self.render(self.launch())
            before = antigravity.running({}, None, "conv-acme")
            self.assertEqual(list(gc.stale_model_reports()), [])
            # A collection plan made before the claim must recheck ownership too.
            candidate = {"action": "remove", "kind": "model-report", "path": str(self.report)}
            with patch.object(gc, "gc_candidates", return_value=[candidate]), \
                    patch.object(gc.jobs, "forget_owner_words"):
                self.assertEqual(gc.gc(lambda _: None), [])
                self.assertEqual(antigravity.running({}, None, "conv-acme"), before)
                antigravity.launched("acme", self.root, None)
                claim = config.STATE / "antigravity-claim.lock"
                claim.unlink()
                recorded = config.session_path("acme").read_bytes()
                self.assertEqual([item["path"] for item in gc.stale_model_reports()], [str(self.report)])
                self.assertEqual(gc.gc(lambda _: None), [str(self.report)])
                self.assertFalse(claim.exists())
                self.assertEqual(config.session_path("acme").read_bytes(), recorded)
            self.assertFalse(self.report.exists())


if __name__ == "__main__":
    unittest.main()
