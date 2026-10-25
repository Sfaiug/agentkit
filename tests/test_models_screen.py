"""`r recommended` on the `c` screen opens `models · <seat>`: a line per role
(tests/test_models_screen_roles.py; each a row the highlight rests on), one knob, `as good
within ‹ 5 ›`, whose ←/→ step `within` a point, never under 0, saved to config.toml at once,
the role lines following, and every model the matrix has a row for under its harness, a mark
each (tests/test_models_screen_marks.py).  On a phone the role lines, the knob and the quality
and cost note are read one at a time.  `r` takes the recommendation as `c`'s line says it
(tests/test_c_recommends_effort.py); Esc returns to `c`.

Offline: a throwaway HOME with a matrix scored from rows written by hand, the catalogs' efforts
faked, the keys fed in, the usage faked.
"""

from contextlib import redirect_stdout
import io
from pathlib import Path
import re
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
from test_c_recommends import Keyboard

LEVELS = {"claude-opus-5-5": ["high", "xhigh", "max"], "gpt-6-astra": ["xhigh"],
          "claude-sonnet-5-5": ["max"], "mimo-pro": ["none", "high"]}


def row(harness, model, effort, *worth, cost=None):
    """A stored row worth `worth` to orchestrate, build and review (None for no score), its
    index run costing `cost` (fixtures.scores)."""
    values = scores.values(**{role: points for role, points in zip(matrix.ROLES, worth)
                              if points is not None})
    if cost is not None:
        values[matrix.COST] = cost
    return {"harness": harness, "model": model, "effort": effort, "name": None, "roles": [],
            "matched": {}, "values": values}


class Screen(Sandbox):
    """`c` on a throwaway HOME whose matrix holds the rows below, driven by keys."""

    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "fable"],
                            {"reviewers": ["fable"], "cwd": "/", "created": 0})
        self.stack.enter_context(patch.object(update, "agentkit_version", return_value="abc1234"))
        scores.read_as_stored(self.stack)     # the boards as stored: none is asked
        self.stack.enter_context(patch.object(usage, "collect", return_value=usage.Readings({})))
        self.stack.enter_context(patch.object(terminal, "layout_width", return_value=100))
        self.stack.enter_context(patch.object(menu, "effort_levels",
                                              side_effect=lambda entry: LEVELS.get(entry["model"], [])))
        self.stack.enter_context(patch.dict("os.environ", {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        # opus at three efforts; astra as good as its xhigh at an eighth of the cost; sonnet,
        # not configured, under the best by more; mimo, which the boards list naming no effort,
        # one row at none; spark, which no board has
        self.store([row("claude", "claude-opus-5-5", "max", 100, 100, 100, cost=8),
                    row("claude", "claude-opus-5-5", "xhigh", 96.55, 96.55, 96.55, cost=4),
                    row("claude", "claude-opus-5-5", "high", 86.2, 86.2, 86.2, cost=2),
                    row("codex", "gpt-6-astra", "xhigh", 84.64, 95.48, 95.75, cost=0.5),
                    row("claude", "claude-sonnet-5-5", "max", 67.86, 84.52, 84.77, cost=7),
                    row("opencode", "mimo-pro", None, None, 50.71, 50.86, cost=0.1),
                    row("muse", "muse-spark-1.3-contributor", None)])
        # each configured model as the screen names it, in full (config.model_name)
        self.opus, self.astra, self.spark = (config.model_name(self.cfg, name)
                                             for name in ("opus", "astra", "spark"))

    def store(self, rows):
        scores.store(rows)

    def screens(self, keys, width=100):
        """Every frame drawn while `c` is driven by `keys` on a screen `width` wide, its
        words one space apart."""
        drawn = io.StringIO()
        with patch.object(terminal, "read_key", side_effect=keys), redirect_stdout(drawn), \
                patch.object(terminal, "layout_width", return_value=width):
            menu.show_config(False, Keyboard(), "fix-api")
        lines = [terminal.plain(line, spaced=True) for line in drawn.getvalue().splitlines()]
        self.assertEqual([line for line in lines if terminal.cells(line) > width], [],
                         "a line runs past the screen")
        return " ".join(" ".join(lines).split())


class ModelsScreen(Screen):
    def test_r_on_c_opens_the_screen_with_the_knob_the_recommendation_and_every_model(self):
        text = self.screens([Key("char", "r"), Key("esc"), Key("esc")])
        self.assertIn("agentkit · models · fix-api", text)
        opus, astra = self.opus, self.astra
        self.assertIn(f"orch {opus} @ xhigh 97 $4.00 a task 0 more as good builds {astra} @ xhigh 95 $0.50 a task "
                      f"1 more as good reviews {astra} @ xhigh 96 $0.50 a task 1 more as good "
                      "as good within ‹ 5 › points of the best", text)
        self.assertIn("quality is 100 less how many points a model is behind the best on the "
                      "public boards; cost is what a task of Artificial Analysis's index run cost it, in "
                      "dollars", text)
        self.assertIn(f"Claude Code › ■ {opus} claude-opus-5-5 □ Sonnet 5.5 claude-sonnet-5-5 Codex", text)
        self.assertIn("↑↓ move space mark r take recommended esc back", text)
        # back on `c`, whose key opens the screen
        self.assertRegex(text, r"esc back.* ↑↓←→ move ⏎ mark r recommended esc back")
        self.assertNotIn("r takes exec and review", text)

    def test_the_knob_steps_within_saved_at_once_and_the_recommendation_follows(self):
        # up past the note, a row, to the knob
        text = self.screens([Key("char", "r"), *[Key("up")] * 2, Key("left"), Key("esc"), Key("esc")])
        self.assertIn("↑↓ move ←→ as good r take recommended esc back", text)
        self.assertEqual(config.load()["within"], 4)
        # within 4, astra's 96 is no longer as good as opus's 100: opus @ xhigh everywhere
        said = f"{self.opus} @ xhigh 97 $4.00 a task 0 more as good"
        self.assertIn(f"orch {said} builds {said} reviews {said} › as good within ‹ 4 ›", text)
        text = self.screens([Key("char", "r"), *[Key("up")] * 2, *[Key("left")] * 6, Key("esc"),
                             Key("esc")])
        self.assertEqual(config.load()["within"], 0)
        said = f"{self.opus} @ max 100 $8.00 a task 0 more as good"
        self.assertIn(f"orch {said} builds {said} reviews {said} › as good within ‹ 0 ›", text)

    def test_on_a_phone_the_cost_gives_way_and_every_line_fits(self):
        # 24 lines hold a page shorter than the screen, wrapped at 40 cells: up through the
        # note, the knob and the role lines, each a row, then down through the models
        with patch.object(terminal, "height", return_value=24):
            text = self.screens([Key("char", "r"), *[Key("up")] * 5, *[Key("down")] * 9,
                                 Key("esc"), Key("esc")], width=40)
        # each role line is read on the page it is highlighted on, its cost given way
        opus, astra = re.escape(self.opus), re.escape(self.astra)
        for said in (f"orch {opus} @ xhigh 97", f"builds {astra} @ xhigh 95",
                     f"reviews {astra} @ xhigh 96"):
            self.assertRegex(text, rf"› {said} .*? ↑↓ move r take recommended esc back")
        self.assertNotIn("$", text.split("models · fix-api")[1])
        self.assertIn("quality is 100 less how many points a model is behind the best on the "
                      "public boards; cost is what a task of Artificial Analysis's index run cost it, in "
                      "dollars", text)
        self.assertIn(f"Muse Code › ■ {self.spark}", text)

    def test_a_line_taller_than_the_page_is_read_a_page_at_a_time(self):
        # seven more models as good to build and review, more lines than a page at 40 cells:
        # up to the first role line, then down through every row, and every line of the
        # screen, the wrapped knob and quality and cost note too, is on some page drawn, even
        # at 40x12
        self.cfg["assess"] = {"claude": ["claude-opus-5-5"], "codex": ["gpt-6-astra"],
                              "opencode": [f"acme-model-{n}" for n in range(7)]}
        config.save(self.cfg)
        self.store([
            row("claude", "claude-opus-5-5", "max", 100, 100, 100, cost=8),
            row("claude", "claude-opus-5-5", "xhigh", 96.55, 96.55, 96.55, cost=4),
            row("codex", "gpt-6-astra", "xhigh", 94.64, 95.48, 95.75, cost=0.5),
            *[row("opencode", f"acme-model-{n}", "high", 96.07, 96.9, 96.61, cost=3 + n / 1000)
              for n in range(7)]])
        bodies, frames, body, frame = [], [], menu.models_body, terminal.frame

        def whole(*args, **kwargs):
            bodies.append(body(*args, **kwargs))
            return bodies[-1]

        def framed(name, page=(), keyline="esc back", **kwargs):
            frames.append(page)
            return frame(name, page, keyline, **kwargs)

        def keys():
            yield Key("char", "r")
            for direction in ("up", "down"):
                yield from [Key(direction)] * len(bodies[0][0])
            yield Key("esc")
            yield Key("esc")

        def said(line):
            return " ".join(terminal.plain(line, spaced=True).split()).lstrip("› ")
        for height in (24, 12):
            with self.subTest(height=height), \
                    patch.object(menu, "models_body", side_effect=whole), \
                    patch.object(terminal, "frame", side_effect=framed), \
                    patch.object(terminal, "height", return_value=height):
                bodies.clear()
                frames.clear()
                self.screens(keys(), width=40)
                shown = {said(line) for page in frames for line in page}
                self.assertEqual([said(line) for line in bodies[0][0] if said(line) not in shown], [])
                self.assertGreater(len(bodies[0][0]), 20)   # more than a page 24 lines tall holds

    def test_r_on_the_screen_takes_the_recommendation(self):
        self.screens([Key("char", "r"), Key("char", "r"), Key("esc"), Key("esc")])
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual((record["orchestrator"], record["workers"], record["reviewers"]),
                         ("opus", ["astra"], ["astra"]))
        astra = config.load()["models"]["astra"]       # the rows at its own effort: it follows
        self.assertEqual((astra["effort"], astra.get("exec_effort"), astra.get("review_effort")),
                         ("xhigh", None, None))


if __name__ == "__main__":
    unittest.main()
