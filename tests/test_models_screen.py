"""`r recommended` on the `c` screen opens `models · <seat>`: every model the matrix has a row
for against the public boards, the best row per role, the rows as good as it and the
recommendation (said why in tests/test_models_screen_says_why.py; each line a row the
highlight rests on), and one knob,
`as good as the best: within ‹ 5 ›`, whose ←/→ step `within` a point, never under 0, saved to
config.toml at once, the recommended and as-good lines following.  One model a row, the
scored ones first by their best quality: full name (config.model_name) or id, harness,
effort between arrows (←/→ step it through the model's own efforts, the numbers following, nothing saved; a row every
board names no effort for stands at every effort of its model), quality
per role at that effort (the recommended row's in `done`'s colour, one as good in the accent,
`-` without a score) and what Artificial Analysis's index run cost it.  On a phone the cost
gives way, each model takes two lines (tests/test_models_screen_phone.py), and the three lines
and the quality and cost note are read one at a time, a page at a time where one is taller
than the page.  `r` takes the recommendation as `c`'s line says it
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
        self.assertIn("as good as the best: within ‹ 5 ›", text)
        opus, astra = self.opus, self.astra
        self.assertIn(f"best orch {opus} @ max 100 $8.00 · builds {opus} @ max 100 $8.00 · reviews "
                      f"{opus} @ max 100 $8.00 as good builds {opus} @ xhigh 97 $4.00 · reviews "
                      f"{opus} @ xhigh 97 $4.00 recommended the cheapest as good: orch {opus} @ "
                      f"xhigh 97 $4.00 · builds {astra} @ xhigh 95 $0.50 · reviews {astra} @ xhigh "
                      "96 $0.50", text)
        self.assertIn("quality is 100 less how many points a model is behind the best on the "
                      "public boards; cost is what a task of Artificial Analysis's index run cost it, in "
                      "dollars", text)
        self.assertIn("model harness effort orch builds reviews cost $", text)
        # the scored models first by their best quality, each at the effort the config runs
        # it at, else its best; a model with one effort has no arrows; mimo's one row at none
        # shows on its first level; spark, which no board has, last at the effort the config
        # runs it at
        self.assertIn(f"› {opus} claude ‹ xhigh › 97 97 97 4.00 "
                      f"{astra} codex xhigh 85 95 96 0.50 "
                      "claude-sonnet-5-5 claude max 68 85 85 7.00 "
                      "mimo-pro opencode ‹ none › - 51 51 0.10 "
                      f"{self.spark} muse xhigh - - - -", text)
        self.assertIn("↑↓ move ←→ effort r take recommended esc back", text)
        # back on `c`, whose key opens the screen
        self.assertRegex(text, r"esc back.* ↑↓←→ move ⏎ choose r recommended esc back")
        self.assertNotIn("r takes exec and review", text)

    def test_the_arrows_step_a_model_s_effort_and_the_numbers_follow_nothing_saved(self):
        text = self.screens([Key("char", "r"), Key("right"), Key("esc"), Key("esc")])
        self.assertIn(f"› {self.opus} claude ‹ max › 100 100 100 8.00 ", text)
        self.assertEqual(config.load()["models"]["opus"]["effort"], "xhigh")
        text = self.screens([Key("char", "r"), Key("left"), Key("left"), Key("esc"), Key("esc")])
        self.assertIn(f"› {self.opus} claude ‹ high › 86 86 86 2.00 ", text)
        # on a model with one effort the arrows do nothing and the key line offers none
        text = self.screens([Key("char", "r"), Key("down"), Key("right"), Key("esc"), Key("esc")])
        self.assertIn(f"› {self.astra} codex xhigh 85 95 96 0.50 ", text)
        # a row at none, the boards naming no effort, counts at every effort of its model
        text = self.screens([Key("char", "r"), *[Key("down")] * 3, Key("right"), Key("esc"),
                             Key("esc")])
        self.assertIn("› mimo-pro opencode ‹ high › - 51 51 0.10 ", text)
        self.assertIn("↑↓ move r take recommended esc back", text)
        # so does a row at the effort the config runs its model at that every board names no
        # effort for: the matrix would match the same board rows at any
        one = row("claude", "claude-opus-5-5", "xhigh", 100, 100, 100, cost=4)
        one["matched"] = {"artificialanalysis.ai": {"model": "Claude Opus 5.5", "effort": None}}
        self.store([one])
        text = self.screens([Key("char", "r"), Key("right"), Key("esc"), Key("esc")])
        self.assertIn(f"› {self.opus} claude ‹ max › 100 100 100 4.00 ", text)

    def test_the_knob_steps_within_saved_at_once_and_the_recommendation_follows(self):
        # up past the note and the three lines that say why, each a row, to the knob
        text = self.screens([Key("char", "r"), *[Key("up")] * 5, Key("left"), Key("esc"), Key("esc")])
        self.assertIn("↑↓ move ←→ as good r take recommended esc back", text)
        self.assertIn("as good as the best: within ‹ 4 ›", text)
        self.assertEqual(config.load()["within"], 4)
        # within 4, astra's 96 is no longer as good as opus's 100: opus @ xhigh everywhere
        said = f"{self.opus} @ xhigh 97 $4.00"
        self.assertIn(f"as good none recommended the cheapest as good: orch {said} · builds "
                      f"{said} · reviews {said}", text)
        text = self.screens([Key("char", "r"), *[Key("up")] * 5, *[Key("left")] * 6, Key("esc"),
                             Key("esc")])
        self.assertIn("as good as the best: within ‹ 0 ›", text)
        self.assertEqual(config.load()["within"], 0)
        said = f"{self.opus} @ max 100 $8.00"
        self.assertIn(f"recommended the cheapest as good: orch {said} · builds {said} · reviews "
                      f"{said}", text)

    def test_on_a_phone_the_cost_gives_way_and_every_line_fits(self):
        # 24 lines hold a page shorter than the lines above the table, wrapped at 40 cells: up
        # through the note and the three that say why, each a row, then down through the models
        with patch.object(terminal, "height", return_value=24):
            text = self.screens([Key("char", "r"), Key("right"), *[Key("up")] * 5, *[Key("down")] * 9,
                                 Key("esc"), Key("esc")], width=40)
        self.assertIn(f"model harness effort orch builds reviews › {self.opus} claude ‹ max › 100 "
                      "100 100", text)
        self.assertNotIn("cost $", text.split("models · fix-api")[1])
        # each line is read whole on the page it is highlighted on, with no arrows to offer
        best, good = (re.escape(f"{self.opus} @ {at}")
                      for at in ("max 100 $8.00", "xhigh 97 $4.00"))
        astra = re.escape(self.astra)
        self.assertRegex(text, rf"› best orch {best} · builds {best} · reviews {best} .*? "
                               r"↑↓ move r take recommended esc back")
        self.assertRegex(text, rf"› as good builds {good} · reviews {good} .*? "
                               r"↑↓ move r take recommended esc back")
        self.assertRegex(text, rf"› recommended the cheapest as good: orch {good} · "
                               rf"builds {astra} @ xhigh 95 \$0\.50 · reviews {astra} @ xhigh 96 \$0\.50 "
                               r".*? ↑↓ move r take recommended esc back")
        self.assertIn("quality is 100 less how many points a model is behind the best on the "
                      "public boards; cost is what a task of Artificial Analysis's index run cost it, in "
                      "dollars", text)
        self.assertIn(f"› {self.spark} muse xhigh - - -", text)

    def test_a_line_taller_than_the_page_is_read_a_page_at_a_time(self):
        # seven more models as good to build and review: `as good` wraps past a page at 40
        # cells.  Up to the knob, then down through every row, and every line of the screen,
        # including the quality and cost note, is on some page drawn, even at 40x12
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
                self.assertGreater(len(bodies[0][0]), 40)   # more than two pages of 17 lines

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
