"""A seat opens on its prompt: its harness's own seat preparation trusts the folder it runs in.

Offline: a temporary HOME and working directory, invented names, the plugins' real
`account_config` and `main`.
"""

import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit.harness import claude, codex


class SeatTrustsItsFolder(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-seat-trust-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.work = self.root / "code" / "atoll ä"
        self.work.mkdir(parents=True)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.work)
        stack = patch.dict(os.environ, {"HOME": str(self.root), "AGENTKIT_ACCOUNT": ""})
        stack.start()
        self.addCleanup(stack.stop)
        for key in ("CLAUDE_CONFIG_DIR", codex.RECEIPT_ENV, codex.CAPTURE_ENV):
            os.environ.pop(key, None)
        self.here = str(self.work.resolve())

    def codex_launch(self):
        seen = []
        with patch.object(codex.os, "execvp", lambda program, cmd: seen.append(cmd)):
            codex.main(["--", "codex", "--yolo"])
        self.assertEqual(seen, [["codex", "--yolo"]])

    def test_claude_usual_login_answers_trust_and_first_run(self):
        (self.root / ".claude.json").write_text(json.dumps(
            {"numStartups": 3, "projects": {"/invented/kept": {"allowedTools": ["Bash"]}}}))
        claude.account_config()
        data = json.loads((self.root / ".claude.json").read_text())
        self.assertIs(data["projects"][self.here]["hasTrustDialogAccepted"], True)
        self.assertEqual(data["projects"]["/invented/kept"], {"allowedTools": ["Bash"]})
        self.assertEqual((data["theme"], data["hasCompletedOnboarding"], data["numStartups"]),
                         ("dark", True, 3))

    def test_codex_trusts_the_folder_once_in_a_file_it_appends_to(self):
        config = self.root / ".codex" / "config.toml"
        self.codex_launch()                       # no ~/.codex yet: made, then written
        self.codex_launch()
        self.assertEqual(tomllib.loads(config.read_text())["projects"],
                         {self.here: {"trust_level": "trusted"}})
        head = 'model = "gpt"   # the owner\'s\n'
        config.write_text(head)
        self.codex_launch()
        self.assertTrue(config.read_text().startswith(head))
        self.assertEqual(tomllib.loads(config.read_text())["projects"][self.here],
                         {"trust_level": "trusted"})

    def test_codex_leaves_a_folder_trusted_in_another_spelling_and_a_broken_file(self):
        config = self.root / ".codex" / "config.toml"
        config.parent.mkdir()
        for text in (f'[projects]\n{json.dumps(self.here, ensure_ascii=False)} = '
                     '{ trust_level = "trusted" }\n',
                     f'[projects."{self.here}"]\ntrust_level = "trusted"\n[unclosed\n'):
            with self.subTest(text=text):
                config.write_text(text)
                self.codex_launch()
                self.assertEqual(config.read_text(), text)


    def test_codex_leaves_a_file_an_appended_table_would_break(self):
        # Another folder's trust kept in an inline table, or `projects` that is no table at
        # all: a `[projects."<dir>"]` after either does not parse, so the file stays as it is.
        config = self.root / ".codex" / "config.toml"
        config.parent.mkdir()
        for text in ('projects = { "/invented/acme" = { trust_level = "trusted" } }\n',
                     'projects = "acme"\n'):
            with self.subTest(text=text):
                config.write_text(text)
                self.codex_launch()
                self.assertEqual(config.read_text(), text)


if __name__ == "__main__":
    unittest.main()
