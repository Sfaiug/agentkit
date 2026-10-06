"""The `c` screen edits the config; nobody edits a file. Offline.

A temporary HOME holds config.toml and the secrets.  The matrix is driven in-process with
`terminal.read_key` fed its keys and a keyboard that is always taken (tests/test_config_matrix.py
drives it on a real pty); Discord reads lines through the patched `menu.read` seam, the way
test_one_way_back drives the screens, and the meters are an empty reading.  What is pinned is
the round trip: a mark writes the seat `fix-api`'s record and never `[defaults]`, effort steps
within its model's own words, add writes a whole block off its three lists, Discord writes the
two secrets, and Version asks no harness anything.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, terminal, update, usage

OWN = """max_runs = 0

[tiers]
A = ["solo"]
B = ["solo"]

[models.solo]
harness = "claude"
model = "m"
effort = "xhigh"
provider = "anthropic"

[providers.anthropic]
mode = "subscription"
"""


class Taken:
    """The menu's keyboard, taken for good: the keys come from the patched `read_key`."""

    def take(self):
        return True

    def give(self):
        pass


class Editor(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".config-editor-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.home), "NO_COLOR": "1",
                                                         "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(config, "HOME", self.home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.home / name.lower()))
        self.stack.enter_context(patch.object(terminal, "width", return_value=100))
        self.stack.enter_context(patch.object(terminal, "height", return_value=30))
        # The Version row's build is a git call; the row is pinned, not the checkout.
        self.stack.enter_context(patch.object(update, "agentkit_version",
                                              return_value="abc1234 · 2026-09-29"))
        self.path = self.home / "config.toml"
        self.path.write_text((REPO / "config.default.toml").read_text())
        config.ensure_dirs()
        config.save_session(config.load(), "fix-api", "opus", ["opus", "astra"])

    def drive(self, *keys, session=None):
        """The `c` screen, on `session` when one is named, against `keys`, then Esc; (the config
        it left, everything it printed)."""
        keys = [terminal.Key(*key) if isinstance(key, tuple) else terminal.Key(key)
                for key in (*keys, "esc")]
        out = io.StringIO()
        with patch.object(terminal, "read_key", side_effect=keys), \
                patch.object(usage, "collect", return_value=usage.Readings({})), \
                redirect_stdout(out):
            left = menu.show_config(False, Taken(), session)
        return left, out.getvalue()

    def record(self):
        return config.load_session(config.load(), "fix-api")

    def steps(self, step, *answers):
        """One step under the matrix against typed `answers`; (everything it printed, the seam)."""
        out = io.StringIO()
        with patch.object(menu, "read", side_effect=list(answers)) as read, redirect_stdout(out):
            step()
        return out.getvalue(), read

    def test_toggling_a_sessions_workers_writes_its_record_and_not_the_defaults(self):
        # fable in, astra out: the list keeps its order and the new one goes last
        before = self.path.read_bytes()
        self.drive("right", "enter", "down", "down", "space", session="fix-api")
        self.assertEqual(self.record()["workers"], ["opus", "fable"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_the_last_worker_may_go_and_its_reviewer_stays(self):
        self.path.write_text(OWN)
        config.save_session(config.load(), "fix-api", "solo", ["solo"])
        before = self.path.read_bytes()
        _, screen = self.drive("right", "enter", session="fix-api")
        self.assertNotIn("exec needs one model", screen)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual((self.record()["workers"], self.record()["reviewers"]), ([], ["solo"]))

    def test_an_old_tiers_file_is_written_in_the_new_shape_by_the_first_save(self):
        self.path.write_text(OWN)
        self.drive("down")
        self.assertEqual(self.path.read_text(), OWN)      # nothing changed: nothing to save
        self.drive("enter")
        saved = tomllib.loads(self.path.read_text())
        self.assertNotIn("tiers", saved)
        self.assertEqual(saved["defaults"], {"orchestrator": "solo", "workers": ["solo"]})
        self.assertEqual(saved["models"]["solo"]["effort"], "max")

    def test_stepping_effort_writes_new_value(self):
        # fable is a claude, xhigh today; its own words run low to max, and go round
        levels = [{"id": "claude-fable-5-1", "label": "Fable 5.1",
                   "efforts": ["low", "medium", "high", "xhigh", "max"]}]
        with patch.object(config, "catalog", return_value=levels):
            for keys, want in ((("enter",), "max"), (("enter",), "low"), (("enter", "enter"), "high")):
                with self.subTest(want=want):
                    self.drive("right", "right", "right", *keys)
                    effort = tomllib.loads(self.path.read_text())["models"]["fable"]["effort"]
                    self.assertEqual(effort, want)

    def test_add_model_writes_complete_entry(self):
        # add a model, then codex, its one model, and its second effort: nothing typed
        levels = [{"id": "gpt-x", "label": "GPT-X", "efforts": ["low", "high"]}]
        with patch.object(config, "catalog", return_value=levels), \
                patch.object(menu, "read") as read:
            self.drive(*["down"] * 7, "enter", "down", "enter", "enter", "down", "enter")
        self.assertEqual(read.call_count, 0)
        models = tomllib.loads(self.path.read_text())["models"]
        self.assertEqual(models["gpt-x"], {"harness": "codex", "model": "gpt-x",
                                           "effort": "high", "provider": "openai"})
        # offered both ways at once, and in neither default until it is chosen there
        left = config.load()
        self.assertIn("gpt-x", config.offered(left))
        self.assertEqual(left["defaults"], {"orchestrator": "opus", "workers": ["opus", "astra"]})
        _, screen = self.drive()
        self.assertIn("  gpt-x ", screen)

    def test_add_cancel_writes_nothing(self):
        before = self.path.read_bytes()
        levels = [{"id": "gpt-x", "label": "GPT-X", "efforts": ["low", "high"]}]
        with patch.object(config, "catalog", return_value=levels):
            self.drive(*["down"] * 7, "enter", "enter", "enter", "esc", "esc", "esc")
        self.assertEqual(self.path.read_bytes(), before)

    def test_unknown_keys_survive_a_write(self):
        text = self.path.read_text()
        text = "mystery = 7\n\n" + text.replace('[models.fable]\nharness = "claude"',
                                                '[models.fable]\nnickname = "f"\nharness = "claude"')
        text += '\n[extra]\nanswer = 42\n\n[extra.nested]\ndeep = true\n'
        self.path.write_text(text)
        levels = [{"id": "claude-fable-5-1", "label": "Fable 5.1",
                   "efforts": ["low", "medium", "high", "xhigh", "max"]}]
        with patch.object(config, "catalog", return_value=levels):
            self.drive("enter")
        again = tomllib.loads(self.path.read_text())
        self.assertEqual(again["mystery"], 7)
        self.assertEqual(again["models"]["fable"]["nickname"], "f")
        self.assertEqual(again["extra"], {"answer": 42, "nested": {"deep": True}})
        self.assertEqual(again["models"]["fable"]["effort"], "max")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_discord_writes_secret_files_0600(self):
        _, screen = self.drive()
        self.assertRegex(screen, r"\n  Discord +not connected\n")
        self.steps(menu.config_discord, "https://hooks/x", "12345")
        for name, want in (("discord_webhook", "https://hooks/x\n"),
                           ("discord_user_id", "12345\n")):
            path = config.SECRETS / name
            self.assertEqual(path.read_text(), want)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        _, screen = self.drive()
        self.assertRegex(screen, r"\n  Discord +id …2345 · webhook …ooks/x\n")
        # An empty answer keeps what is there.
        before = {name: (config.SECRETS / name).read_bytes()
                  for name in ("discord_webhook", "discord_user_id")}
        self.steps(menu.config_discord, "", "")
        for name, blob in before.items():
            self.assertEqual((config.SECRETS / name).read_bytes(), blob)

    def test_the_version_is_read_once_per_visit_and_no_harness_is_asked(self):
        # One git call a visit, no matter how often the screen redraws underneath it, and no
        # harness binary or network at all: a slow one must not freeze the screen.
        with patch.object(update, "version") as versions, \
                patch.object(update, "agentkit_version", return_value="abc1234") as build, \
                patch.object(update, "behind") as asked:
            self.drive("down", "down", "right")   # four draws
            self.drive("x")                       # a key that does nothing: two draws
        self.assertEqual((versions.call_count, build.call_count, asked.call_count), (0, 2, 0))

    def test_a_failed_save_changes_nothing_and_says_why_on_a_phone(self):
        levels = [{"id": "claude-fable-5-1", "label": "Fable 5.1",
                   "efforts": ["low", "medium", "high", "xhigh", "max"]}]
        before = self.path.read_bytes()
        with patch.object(config, "save", side_effect=OSError("disk full")), \
                patch.object(config, "catalog", return_value=levels), \
                patch.object(terminal, "width", return_value=40), \
                patch.object(terminal, "height", return_value=24):
            for keys in (("enter",), ("right", "enter"), ("right", "right", "enter"),
                         ("right", "right", "right", "enter")):
                with self.subTest(keys=keys):
                    left, screen = self.drive(*keys)
                    self.assertEqual(left["defaults"], {"orchestrator": "opus",
                                                        "workers": ["opus", "astra"]})
                    self.assertEqual(left["models"]["fable"]["effort"], "xhigh")
                    said = [frame.splitlines() for frame in screen.split("agentkit · config")
                            if "config: disk full" in frame]
                    self.assertTrue(said, screen)
                    self.assertLessEqual(len(said[0]), 23)
        self.assertEqual(self.path.read_bytes(), before)

    def test_a_model_called_like_a_row_is_a_model(self):
        self.path.write_text(self.path.read_text() + '\n[models.Discord]\nharness = "claude"\n'
                             'model = "m"\neffort = "high"\nprovider = "anthropic"\n')
        with patch.object(menu, "config_discord") as step:
            # fable, opus, then Discord, a Claude
            self.drive("down", "down", "right", "enter", session="fix-api")
        self.assertEqual(step.call_count, 0)
        self.assertEqual(self.record()["workers"], ["opus", "astra", "Discord"])

    def test_main_screen_lists_values(self):
        _, screen = self.drive(session="fix-api")
        self.assertTrue(screen.startswith("agentkit · config · fix-api"), screen)
        for bit in ("orch  exec  review  effort", "Claude", "opus    claude", "●", "■", "□",
                    "‹ xhigh ›", "add a model", "Discord", "Version        abc1234 · 2026-09-29",
                    "esc back"):
            self.assertIn(bit, screen)
        self.assertNotIn("Update", screen)
        self.assertNotIn("harnesses", screen)


if __name__ == "__main__":
    unittest.main()
