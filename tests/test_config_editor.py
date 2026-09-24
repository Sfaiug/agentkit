"""The `c` screen edits the config; nobody edits a file. Offline.

A temporary HOME holds config.toml and the secrets.  The matrix is driven in-process with
`terminal.read_key` fed its keys and a keyboard that is always taken (tests/test_config_matrix.py
drives it on a real pty); Discord and Update read lines through the patched `menu.read` seam,
the way test_v5u drives the screens.  What is pinned is the round trip: a mark writes the
default orchestrator and the default workers that `n` then takes with Enter, effort steps
within its model's own words, add writes a whole block off its three lists, Discord writes the
two secrets, and Update refuses while a session is working.
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
from agentkit import config, menu, orch, terminal, update, watch

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
        # The update row's versions are subprocesses; the rows are pinned, not the binaries.
        self.stack.enter_context(patch.object(update, "version", return_value=""))
        self.stack.enter_context(patch.object(update, "agentkit_version", return_value="abc1234"))
        self.stack.enter_context(patch.object(update, "agentkit_newer", return_value=""))
        self.path = self.home / "config.toml"
        self.path.write_text((REPO / "config.default.toml").read_text())
        config.ensure_dirs()

    def drive(self, *keys):
        """The `c` screen against `keys`, then `q`; (the config it left, everything it printed)."""
        keys = [terminal.Key(*key) if isinstance(key, tuple) else terminal.Key(key)
                for key in (*keys, ("char", "q"))]
        out = io.StringIO()
        with patch.object(terminal, "read_key", side_effect=keys), redirect_stdout(out):
            left = menu.show_config(False, Taken())
        return left, out.getvalue()

    def steps(self, step, *answers):
        """One step under the matrix against typed `answers`; (everything it printed, the seam)."""
        out = io.StringIO()
        with patch.object(menu, "read", side_effect=list(answers)) as read, redirect_stdout(out):
            step()
        return out.getvalue(), read

    def test_toggling_default_workers_is_what_enter_takes(self):
        # fable in, astra out: the list keeps its order and the new one goes last
        left, _ = self.drive("right", "enter", "down", "down", "space")
        self.assertEqual(tomllib.loads(self.path.read_text())["defaults"]["workers"],
                         ["opus", "fable"])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        # every model stays a choice; Enter takes the two the screen left
        with patch.object(terminal, "ask", return_value="") as ask:
            self.assertEqual(orch.prompt_workers(left), ["opus", "fable"])
        self.assertEqual(ask.call_args[0][1], "opus fable")
        self.assertEqual(ask.call_args[0][2], config.offered(left))

    def test_the_last_default_worker_cannot_go(self):
        self.path.write_text(OWN)
        before = self.path.read_bytes()
        _, screen = self.drive("right", "enter")
        self.assertIn("the default workers need one model", screen)
        self.assertEqual(self.path.read_bytes(), before)

    def test_choosing_the_default_orchestrator(self):
        self.drive("down", "down", "enter")
        self.assertEqual(tomllib.loads(self.path.read_text())["defaults"]["orchestrator"], "astra")
        self.assertEqual(orch.choose(config.load(), {})[0], "astra")
        # an old [tiers] file is written in the new shape by the first save, and only then
        self.path.write_text(OWN)
        self.assertEqual(self.path.read_text(), OWN)
        self.drive("enter")
        self.assertEqual(self.path.read_text(), OWN)      # the one there is: nothing to save
        self.drive("right", "right", "enter")
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
                    self.drive("right", "right", *keys)
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
        self.drive("right", "enter")
        again = tomllib.loads(self.path.read_text())
        self.assertEqual(again["mystery"], 7)
        self.assertEqual(again["models"]["fable"]["nickname"], "f")
        self.assertEqual(again["extra"], {"answer": 42, "nested": {"deep": True}})
        self.assertEqual(again["defaults"]["workers"], ["opus", "astra", "fable"])

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
        self.assertRegex(screen, r"\n  Discord +connected\n")
        # An empty answer keeps what is there.
        before = {name: (config.SECRETS / name).read_bytes()
                  for name in ("discord_webhook", "discord_user_id")}
        self.steps(menu.config_discord, "", "")
        for name, blob in before.items():
            self.assertEqual((config.SECRETS / name).read_bytes(), blob)

    def test_update_refuses_while_working(self):
        seats = [{"name": "a"}, {"name": "b"}]
        with patch.object(orch, "listing", return_value=seats), \
                patch.object(watch, "session_state", return_value={"word": "working"}), \
                patch.object(update, "main") as harm, \
                patch.object(update, "update_agentkit") as selfm:
            screen, _ = self.steps(lambda: menu.config_update(config.load()), "q")
        self.assertIn("2 sessions are working; try when they are done", screen)
        self.assertEqual(harm.call_count, 0)
        self.assertEqual(selfm.call_count, 0)

    def test_update_versions_are_read_once_per_visit(self):
        # One version call per harness a visit, no matter how often the screen redraws
        # underneath it: a slow harness binary must not freeze it.
        harnesses = len(update.harnesses(config.load()))
        with patch.object(update, "version", return_value="") as versions:
            self.drive("down", "down", "right")   # four draws
            self.drive("x")                       # a key that does nothing: two draws
        self.assertEqual(versions.call_count, 2 * harnesses)

    def test_a_failed_save_changes_nothing_and_says_why_on_a_phone(self):
        levels = [{"id": "claude-fable-5-1", "label": "Fable 5.1",
                   "efforts": ["low", "medium", "high", "xhigh", "max"]}]
        before = self.path.read_bytes()
        with patch.object(config, "save", side_effect=OSError("disk full")), \
                patch.object(config, "catalog", return_value=levels), \
                patch.object(terminal, "width", return_value=40), \
                patch.object(terminal, "height", return_value=24):
            for keys in (("enter",), ("right", "enter"), ("right", "right", "enter")):
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
        self.path.write_text(self.path.read_text() + '\n[models.Update]\nharness = "claude"\n'
                             'model = "m"\neffort = "high"\nprovider = "anthropic"\n')
        with patch.object(menu, "config_update") as step:
            self.drive("down", "down", "right", "enter")     # fable, opus, then Update, a Claude
        self.assertEqual(step.call_count, 0)
        self.assertEqual(tomllib.loads(self.path.read_text())["defaults"]["workers"],
                         ["opus", "astra", "Update"])

    def test_main_screen_lists_values(self):
        _, screen = self.drive()
        self.assertTrue(screen.startswith("agentkit · config"), screen)
        for bit in ("orchestrator  worker  effort", "Claude", "opus    claude", "●", "■", "□",
                    "‹ xhigh ›", "add a model", "Discord", "Update",
                    "abc1234 · up to date · harnesses", "esc back"):
            self.assertIn(bit, screen)
        with patch.object(update, "agentkit_newer", return_value="def5678"):
            _, screen = self.drive()
        self.assertIn("abc1234 · def5678 available", screen)


if __name__ == "__main__":
    unittest.main()
