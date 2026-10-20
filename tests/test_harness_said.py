"""Every harness reads a seat's conversation back from its own store as plain turns: what the
user side typed and the model's visible answers, oldest first.  Each fixture is that harness's
own store format with invented content -- a tool call, its result and a thinking block among
the turns -- placed where the harness keeps it under a temporary HOME."""

from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"
sys.path.insert(0, str(REPO))
from agentkit import config, harness
from agentkit.harness import claude

SAID = [{"who": "user", "text": "Rename the acme report to fix-api."},
        {"who": "model", "text": "I'll look at the report first."},
        {"who": "model", "text": "Renamed acme/report.md to acme/fix-api.md."},
        {"who": "user", "text": "Thanks, that is all."},
        {"who": "model", "text": "Done."}]
CWD = "/tmp/acme"
GROK = "6f1d2c3b-4a5e-4f60-8a71-9b8c7d6e5f40"   # the session its updates name


class Said(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-said-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        for patcher in (patch.dict(os.environ, {"HOME": tmp.name}),
                        patch.object(config, "HOME", self.home / ".agentkit")):
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("XDG_DATA_HOME", "GROK_HOME"):
            os.environ.pop(name, None)     # patch.dict puts them back

    def place(self, fixture, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        if fixture.endswith(".sql"):
            with closing(sqlite3.connect(path)) as db:
                db.executescript((FIXTURES / fixture).read_text())
        else:
            shutil.copy(FIXTURES / fixture, path)

    def test_each_harness_gives_the_turns_and_nothing_else(self):
        token = "0" * 32
        rollout = self.home / ".codex/sessions/2026/10/20/rollout-acme.jsonl"
        stores = {
            "claude": ("said-claude.jsonl", {"cwd": CWD, "account": "default"}, "c0ffee",
                       claude.transcript_path({"cwd": CWD}, "c0ffee")),
            "codex": ("said-codex.jsonl", {"codex_launch": token}, "thread", rollout),
            "grokbuild": ("said-grokbuild-updates.jsonl", {"cwd": CWD}, GROK,
                          self.home / ".grok/sessions" / quote(CWD, safe="") / GROK
                          / "updates.jsonl"),
            "muse": ("said-muse-session.jsonl", {}, "m1",
                     self.home / ".local/share/muse/sessions/2026/10/20/m1/session.jsonl"),
            "opencode": ("said-opencode.sql", {}, "ses_0fa1c2d3e4ffAcmeFixture01",
                         self.home / ".local/share/opencode/opencode.db"),
            "antigravity": ("said-antigravity.sql", {}, "a1",
                            self.home / ".gemini/antigravity-cli/conversations/a1.db"),
        }
        config.STATE.mkdir(parents=True)
        (config.STATE / f"codex-launch-{token}.json").write_text(json.dumps(
            {"launch": token, "event": {"transcript_path": str(rollout)}}))
        for name, (fixture, record, conversation, path) in stores.items():
            with self.subTest(name):
                plugin = harness.load(name)
                self.assertIsNone(plugin.said(record, CWD, conversation), "before its store is")
                self.place(fixture, path)
                self.assertEqual(plugin.said(record, CWD, conversation), SAID)

    def test_a_harness_without_a_reader_says_none(self):
        self.assertIsNone(harness.load("acme").said({}, CWD, "c0ffee"))


if __name__ == "__main__":
    unittest.main()
