"""`r` on the models screen (`r recommended` on `c`) also sets the recommended effort for the
executor and the reviewer on the model entry.

A recommended row is a model at an effort; the entry that runs that model on that harness is
the one running it in that role (`matrix.runs`) or the first such entry, and the line names it
on both screens.  `r` marks it for the role and sets
the row's effort as the entry's `exec_effort` or `review_effort`, unset where the row's effort
is the entry's own, so the role runs at what the boards recommend while the entry's effort
stays the owner's; the orchestrator's row is only said.

Offline: a throwaway HOME with a stored matrix written by hand, the keys fed in, the usage faked
(tests/test_c_recommends.py's).
"""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures import scores
from fixtures.sandbox import Sandbox
from agentkit import config, matrix, menu, terminal, update, usage
from agentkit.terminal import Key
from test_c_recommends import Keyboard, row


class RecommendsEffort(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, "fix-api", "fable", ["fable", "astra"],
                            {"reviewers": ["astra"], "cwd": "/", "created": 0})
        self.stack.enter_context(patch.object(update, "agentkit_version", return_value="abc1234"))
        scores.read_as_stored(self.stack)     # the boards as stored: none is asked
        self.stack.enter_context(patch.object(usage, "collect", return_value=usage.Readings({})))
        self.stack.enter_context(patch.object(terminal, "layout_width", return_value=100))
        self.stack.enter_context(patch.dict("os.environ", {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))

    def store(self, rows):
        scores.store(rows)

    def screen(self, keys):
        drawn = io.StringIO()
        with patch.object(terminal, "read_key", side_effect=keys), redirect_stdout(drawn):
            menu.show_config(False, Keyboard(), "fix-api")
        return " ".join(terminal.plain(drawn.getvalue()).split())

    def entry(self, name):
        return config.load()["models"][name]

    def test_r_marks_the_entry_running_the_model_and_sets_its_effort_for_the_role(self):
        # the entries run at xhigh; the rows at max and high are nobody's own, so the entry
        # running that model on that harness is the one
        self.store([row("claude", "claude-fable-5-1", "max", orchestrate=100),
                    row("claude", "claude-opus-5-5", "max", execute=100),
                    row("codex", "gpt-6-astra", "high", review=100)])
        self.screen([Key("char", "r"), Key("char", "r"), Key("esc"), Key("esc")])
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual((record["orchestrator"], record["workers"], record["reviewers"]),
                         ("fable", ["opus"], ["astra"]))
        self.assertEqual((self.entry("opus")["effort"], self.entry("opus")["exec_effort"]), ("xhigh", "max"))
        self.assertEqual((self.entry("astra")["effort"], self.entry("astra")["review_effort"]), ("xhigh", "high"))
        self.assertNotIn("review_effort", self.entry("opus"))
        # the orchestrator's row is only said: its entry is untouched
        self.assertEqual(self.entry("fable"), self.cfg["models"]["fable"])

    def test_the_models_screen_names_the_entry_r_marks_where_two_run_the_model(self):
        # opus-max runs opus's model at max, the recommended rows' effort: the screen names
        # the entry running the row in the role, not the first running the model, by its full
        # name (config.model_name), and r marks it
        self.cfg["models"]["opus-max"] = {**self.cfg["models"]["opus"], "effort": "max"}
        config.save(self.cfg)
        self.store([row("claude", "claude-opus-5-5", "max", execute=100, review=100)])
        text = self.screen([Key("char", "r"), Key("char", "r"), Key("esc"), Key("esc")])
        said = f"{config.model_name(self.cfg, 'opus-max')} @ max 100"
        self.assertIn(f"orch none builds {said} reviews {said}", text)
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual((record["workers"], record["reviewers"]), (["opus-max"], ["opus-max"]))
        self.assertNotIn("exec_effort", self.entry("opus-max"))

    def test_a_row_at_the_entry_s_own_effort_unsets_the_role_s_key(self):
        self.cfg["models"]["opus"]["exec_effort"] = "max"
        self.cfg["models"]["astra"]["review_effort"] = "low"
        config.save(self.cfg)
        self.store([row("claude", "claude-opus-5-5", "xhigh", "opus", execute=100),
                    row("codex", "gpt-6-astra", "xhigh", review=100)])
        self.screen([Key("char", "r"), Key("char", "r"), Key("esc"), Key("esc")])
        self.assertNotIn("exec_effort", self.entry("opus"))
        self.assertNotIn("review_effort", self.entry("astra"))
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual((record["workers"], record["reviewers"]), (["opus"], ["astra"]))
        # a row at no effort runs at the entry's: the key goes too
        self.cfg["models"]["opus"]["exec_effort"] = "max"
        config.save(self.cfg)
        self.store([row("claude", "claude-opus-5-5", None, execute=100)])
        self.screen([Key("char", "r"), Key("char", "r"), Key("esc"), Key("esc")])
        self.assertNotIn("exec_effort", self.entry("opus"))

    def test_a_config_that_cannot_be_saved_changes_no_mark(self):
        self.store([row("claude", "claude-opus-5-5", "max", execute=100)])
        with patch.object(config, "save", side_effect=OSError("read-only")):
            text = self.screen([Key("char", "r"), Key("char", "r"), Key("esc"), Key("esc")])
        self.assertIn("config: read-only", text)
        self.assertNotIn("exec_effort", self.entry("opus"))
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual(record["workers"], ["fable", "astra"])


if __name__ == "__main__":
    unittest.main()
