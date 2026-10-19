"""The `c` screen shows what `ak models` recommends beside a seat's marks, and `r`, or a click
on `r recommended`, opens the models screen (tests/test_models_screen.py), where `r` takes it.

The line a seat's highlighted model opens ends with the roles `ak models` recommends it for,
read off the matrix as last computed (`matrix.stored`, `matrix.recommended`); `r` there
makes the recommended executor and reviewer the seat's marks where an entry in the config as it
stands runs that model (`matrix.runs`; tests/test_c_recommends_effort.py: at the row's effort),
saved to its record at once, and says why when it cannot; the orchestrator is only said, since
moving the seat asks first.  With nothing computed no model is recommended and `r` is no key.

Offline: a throwaway HOME with a stored matrix written by hand, the keys fed in, the usage faked.
"""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import config, matrix, menu, terminal, update, usage
from agentkit.terminal import Key


class Keyboard:
    def take(self):
        return True


# two of each role's measures: half of its own, too few of another's for a score there
MEASURES = {"orchestrate": ("arena.agent", "arena.agent_steerability"),
            "execute": ("livebench.coding", "aa.evaluations.artificial_analysis_coding_index"),
            "review": (matrix.INTEL, "livebench.reasoning")}


def row(harness, model, effort, name=None, **valued):
    """A stored row worth `valued[role]` on two of each such role's measures, so reading it
    (`matrix.stored`) scores it for those roles alone; a configured one runs in every role it
    is valued for."""
    return {"harness": harness, "model": model, "effort": effort, "name": name,
            "values": {column: value for role, value in valued.items() for column in MEASURES[role]},
            "roles": [role for role in matrix.ROLES if name and role in valued], "matched": {}}


class Recommends(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"],
                            {"reviewers": ["astra"], "cwd": "/", "created": 0})
        self.stack.enter_context(patch.object(update, "agentkit_version", return_value="abc1234"))
        self.stack.enter_context(patch.object(usage, "collect", return_value=usage.Readings({})))
        self.stack.enter_context(patch.object(terminal, "layout_width", return_value=100))
        self.stack.enter_context(patch.dict("os.environ", {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))

    def store(self, rows):
        matrix.cache_path().parent.mkdir(parents=True, exist_ok=True)
        matrix.cache_path().write_text(json.dumps({"matrix": {"computed_at": 1, "config": [], "rows": rows}}))

    def screen(self, keys):
        drawn = io.StringIO()
        with patch.object(terminal, "read_key", side_effect=keys), redirect_stdout(drawn):
            menu.show_config(False, Keyboard(), "fix-api")
        lines = [terminal.plain(line) for line in drawn.getvalue().splitlines()]
        self.assertEqual([line for line in lines if terminal.cells(line) > 100], [],
                         "a line runs past the screen")
        return " ".join(" ".join(lines).split())      # one space between words

    def test_the_line_names_each_role_s_row_and_r_takes_the_configured_ones(self):
        self.store([row("claude", "claude-sonnet-4-6", "max", orchestrate=100, execute=50),
                    row("claude", "claude-fable-5-1", "xhigh", "fable", execute=90),
                    row("codex", "gpt-6-astra", "xhigh", "astra", review=100)])
        text = self.screen([Key("esc")])
        self.assertRegex(text, r"fable runs on [^·]+ · recommended to build ")
        self.assertIn("⏎ mark r recommended esc back", text)
        # r opens the models screen and takes nothing by itself
        text = self.screen([Key("char", "r"), Key("esc"), Key("esc")])
        self.assertIn("agentkit · models · fix-api", text)
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual((record["workers"], record["reviewers"]), (["opus", "astra"], ["astra"]))
        self.screen([Key("char", "r"), Key("char", "r"), Key("esc"), Key("esc")])
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual((record["orchestrator"], record["workers"], record["reviewers"]),
                         ("opus", ["fable"], ["astra"]))

    def test_a_click_on_r_recommended_does_what_r_does(self):
        # the click opens the models screen; r there takes
        self.store([row("claude", "claude-fable-5-1", "xhigh", "fable", execute=100),
                    row("codex", "gpt-6-astra", "xhigh", "astra", review=100)])
        spots, frame = {}, terminal.frame

        def framed(*args, **kwargs):
            drawn = frame(*args, **kwargs)
            spots.update(drawn)
            return drawn

        def keys():         # the click lands on `r` where the drawn key line has it
            yield next(Key("click", col=first, row=line) for line, (_, cells) in spots.items()
                       for first, _, cell in cells if cell == "r")
            yield Key("char", "r")
            yield Key("esc")
            yield Key("esc")
        with patch.object(terminal, "frame", side_effect=framed):
            self.screen(keys())
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual((record["workers"], record["reviewers"]), (["fable"], ["astra"]))

    def test_an_unconfigured_recommendation_is_said_and_nothing_changes(self):
        self.store([row("claude", "claude-sonnet-4-6", "max", execute=100), row("codex", "gpt-6-nano", "max", review=100)])
        text = self.screen([Key("char", "r"), Key("char", "r"), Key("esc"), Key("esc")])
        self.assertIn("nothing to take: the recommended rows are not configured models", text)
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual((record["workers"], record["reviewers"]), (["opus", "astra"], ["astra"]))
        # one of the two configured: that one is taken, the other mark stays
        self.store([row("claude", "claude-sonnet-4-6", "max", execute=100), row("codex", "gpt-6-astra", "xhigh", "astra", review=100)])
        self.screen([Key("char", "r"), Key("char", "r"), Key("esc"), Key("esc")])
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual((record["workers"], record["reviewers"]), (["opus", "astra"], ["astra"]))

    def test_a_recommended_model_removed_on_the_screen_is_not_configured_at_once(self):
        # the matrix still names fable: the config as this screen left it decides, and r
        # takes the other.  Its label, Enter, down to `Remove`, Enter asks, `Remove` picked.
        self.store([row("claude", "claude-fable-5-1", "xhigh", "fable", execute=100),
                    row("claude", "claude-opus-5-5", "xhigh", "opus", review=100)])
        text = self.screen([Key("left"), Key("enter"), *[Key("down")] * 4, Key("enter"),
                            Key("down"), Key("enter"), Key("char", "r"), Key("char", "r"),
                            Key("esc"), Key("esc")])
        self.assertNotIn("fable", config.load()["models"])
        self.assertRegex(text, r"opus runs on [^·]+ · recommended to review ↑↓←→ move")
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual((record["workers"], record["reviewers"]), (["opus", "astra"], ["opus"]))

    def test_on_a_short_screen_the_line_keeps_whole_parts_that_fit_with_the_note(self):
        # fable spent, recommended for every role and the last reviewer: the refusal and a row
        # of the page keep their lines, and the model's line drops the parts that do not fit
        self.store([row("claude", "claude-fable-5-1", "xhigh", "fable",
                        orchestrate=100, execute=100, review=100)])
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"],
                            {"reviewers": ["fable"], "cwd": "/", "created": 0})
        spent = usage.Readings({"anthropic": {"meters": [{
            "name": "weekly_all", "used": 100, "exhausted": True, "resets_at": 96400}]}})
        heights, frame = [], terminal.frame

        def framed(name, body=(), keyline="esc back", **kwargs):
            heights.append(3 + len(body) + len(terminal.key_line(keyline)))
            return frame(name, body, keyline, **kwargs)
        with patch.object(terminal, "layout_width", return_value=40), \
                patch.object(terminal, "height", return_value=12), \
                patch.object(usage, "collect", return_value=spent), \
                patch.object(terminal, "frame", side_effect=framed):
            text = self.screen([Key("right"), Key("right"), Key("enter"), Key("esc")])
        # every page leaves the screen's last two rows (matrix_page)
        self.assertEqual(max(heights), 10, heights)
        self.assertIn("at least one model reviews", text)
        self.assertIn("fable runs on Claude", text)
        self.assertNotIn("recommended to orchestrate, build", text)

    def test_with_nothing_computed_no_model_is_recommended_and_r_is_no_key(self):
        text = self.screen([Key("char", "r"), Key("esc")])
        self.assertRegex(text, r"fable runs on [^·]+ ↑↓←→ move")
        self.assertNotIn("recommended", text)
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual((record["workers"], record["reviewers"]), (["opus", "astra"], ["astra"]))
        # without a seat nothing is recommended
        self.store([row("claude", "claude-fable-5-1", "xhigh", "fable", execute=100)])
        with patch.object(terminal, "read_key", side_effect=[Key("esc")]), \
                redirect_stdout(io.StringIO()) as drawn:
            menu.show_config(False, Keyboard(), None)
        self.assertNotIn("recommended", terminal.plain(drawn.getvalue()))


if __name__ == "__main__":
    unittest.main()
