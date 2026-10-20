"""`r recommended` on the `c` screen opens `models · <seat>`: every model the matrix has a row
for against the public boards, the best row per role, the rows as good as it and the
recommendation (said why in tests/test_models_screen_says_why.py; each line a row the
highlight rests on), and one knob,
`as good as the best: within ‹ 5 ›`, whose ←/→ step `within` a point, never under 0, saved to
config.toml at once, the recommended and as-good lines following.  One model a row, the
scored ones first by their best quality: config name or id, harness, effort between arrows
(←/→ step it through the model's own efforts, the numbers following, nothing saved; a row every
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
from test_c_recommends import Keyboard

CODING = "aa.evaluations.artificial_analysis_coding_index"
AGENTIC = "aa.evaluations.artificial_analysis_agentic_index"
LEVELS = {"claude-opus-5-5": ["high", "xhigh", "max"], "gpt-6-astra": ["xhigh"],
          "claude-sonnet-5-5": ["max"], "mimo-pro": ["none", "high"]}


def row(harness, model, effort, coding, agentic, intel, cost, agent=None):
    values = {CODING: coding, AGENTIC: agentic, matrix.INTEL: intel, matrix.COST: cost}
    if agent is not None:
        values["arena.agent_task_outcome_explicit"] = agent
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
        # opus at three efforts, told apart by the intelligence index; astra as good as its
        # xhigh at a tenth of the cost; sonnet, not configured, under the best by more; mimo,
        # which the boards list naming no effort, one row at none
        rows = matrix.scored([
            row("claude", "claude-opus-5-5", "max", 60, 70, 58, 8000, agent=0.2),
            row("claude", "claude-opus-5-5", "xhigh", 60, 70, 56, 4000),
            row("claude", "claude-opus-5-5", "high", 60, 70, 50, 2000),
            row("codex", "gpt-6-astra", "xhigh", 58, 66, 55, 500, agent=0.15),
            row("claude", "claude-sonnet-5-5", "max", 50, 60, 50, 7000, agent=0.1),
            row("opencode", "mimo-pro", None, 30, 36, 30, 100),
            row("muse", "muse-spark-1.3-contributor", None, 0, 0, 0, 0)])
        rows[-1]["values"] = {}                       # no board has spark
        rows[-1]["scores"] = {role: None for role in matrix.ROLES}
        self.store(rows)

    def store(self, rows):
        matrix.cache_path().parent.mkdir(parents=True, exist_ok=True)
        matrix.cache_path().write_text(json.dumps({"matrix": {"computed_at": 1, "config": [],
                                                              "rows": rows}}))

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
        self.assertIn("best orch opus @ max 100 $8000 · builds opus @ max 100 $8000 · reviews opus @ max "
                      "100 $8000 as good builds opus @ xhigh 97 $4000 · reviews opus @ xhigh 97 $4000 "
                      "recommended the cheapest as good: orch opus @ xhigh 97 $4000 · builds astra @ "
                      "xhigh 95 $500 · reviews astra @ xhigh 96 $500", text)
        self.assertIn("quality is a model's share of the best on the public boards, out of 100; "
                      "cost is what Artificial Analysis's index run cost it, in dollars", text)
        self.assertIn("model harness effort orch builds reviews cost $", text)
        # the scored models first by their best quality, each at the effort the config runs
        # it at, else its best; a model with one effort has no arrows; mimo's one row at none
        # shows on its first level; spark, which no board has, last at the effort the config
        # runs it at
        self.assertRegex(text, r"› opus claude ‹ xhigh › 97 97 97 4000 "
                              r"astra codex xhigh 85 95 96 500 "
                              r"claude-sonnet-5-5 claude max 68 85 85 7000 "
                              r"mimo-pro opencode ‹ none › - 51 51 100 "
                              r"spark muse xhigh - - - -")
        self.assertIn("↑↓ move ←→ effort r take recommended esc back", text)
        # back on `c`, whose key opens the screen
        self.assertRegex(text, r"esc back.* ↑↓←→ move ⏎ choose r recommended esc back")
        self.assertNotIn("r takes exec and review", text)

    def test_the_arrows_step_a_model_s_effort_and_the_numbers_follow_nothing_saved(self):
        text = self.screens([Key("char", "r"), Key("right"), Key("esc"), Key("esc")])
        self.assertRegex(text, r"› opus claude ‹ max › 100 100 100 8000 ")
        self.assertEqual(config.load()["models"]["opus"]["effort"], "xhigh")
        text = self.screens([Key("char", "r"), Key("left"), Key("left"), Key("esc"), Key("esc")])
        self.assertRegex(text, r"› opus claude ‹ high › 86 86 86 2000 ")
        # on a model with one effort the arrows do nothing and the key line offers none
        text = self.screens([Key("char", "r"), Key("down"), Key("right"), Key("esc"), Key("esc")])
        self.assertRegex(text, r"› astra codex xhigh 85 95 96 500 ")
        # a row at none, the boards naming no effort, counts at every effort of its model
        text = self.screens([Key("char", "r"), *[Key("down")] * 3, Key("right"), Key("esc"),
                             Key("esc")])
        self.assertIn("› mimo-pro opencode ‹ high › - 51 51 100 ", text)
        self.assertIn("↑↓ move r take recommended esc back", text)
        # so does a row at the effort the config runs its model at that every board names no
        # effort for: the matrix would match the same board rows at any
        one = row("claude", "claude-opus-5-5", "xhigh", 60, 70, 56, 4000, agent=0.2)
        one["matched"] = {"artificialanalysis.ai": {"model": "Claude Opus 5.5", "effort": None}}
        self.store(matrix.scored([one]))
        text = self.screens([Key("char", "r"), Key("right"), Key("esc"), Key("esc")])
        self.assertIn("› opus claude ‹ max › 100 100 100 4000 ", text)

    def test_the_knob_steps_within_saved_at_once_and_the_recommendation_follows(self):
        # up past the note and the three lines that say why, each a row, to the knob
        text = self.screens([Key("char", "r"), *[Key("up")] * 5, Key("left"), Key("esc"), Key("esc")])
        self.assertIn("↑↓ move ←→ as good r take recommended esc back", text)
        self.assertIn("as good as the best: within ‹ 4 ›", text)
        self.assertEqual(config.load()["within"], 4)
        # within 4, astra's 96 is no longer as good as opus's 100: opus @ xhigh everywhere
        self.assertIn("as good none recommended the cheapest as good: orch opus @ xhigh 97 $4000 · "
                      "builds opus @ xhigh 97 $4000 · reviews opus @ xhigh 97 $4000", text)
        text = self.screens([Key("char", "r"), *[Key("up")] * 5, *[Key("left")] * 6, Key("esc"),
                             Key("esc")])
        self.assertIn("as good as the best: within ‹ 0 ›", text)
        self.assertEqual(config.load()["within"], 0)
        self.assertIn("recommended the cheapest as good: orch opus @ max 100 $8000 · builds opus @ max "
                      "100 $8000 · reviews opus @ max 100 $8000", text)

    def test_on_a_phone_the_cost_gives_way_and_every_line_fits(self):
        # 24 lines hold a page shorter than the lines above the table, wrapped at 40 cells: up
        # through the note and the three that say why, each a row, then down through the models
        with patch.object(terminal, "height", return_value=24):
            text = self.screens([Key("char", "r"), Key("right"), *[Key("up")] * 5, *[Key("down")] * 9,
                                 Key("esc"), Key("esc")], width=40)
        self.assertIn("model harness effort orch builds reviews › opus claude ‹ max › 100 100 100",
                      text)
        self.assertNotIn("cost $", text.split("models · fix-api")[1])
        # each line is read whole on the page it is highlighted on, with no arrows to offer
        self.assertRegex(text, r"› best orch opus @ max 100 \$8000 · builds opus @ max 100 \$8000 · "
                               r"reviews opus @ max 100 \$8000 .*? ↑↓ move r take recommended esc back")
        self.assertRegex(text, r"› as good builds opus @ xhigh 97 \$4000 · reviews opus @ xhigh 97 "
                               r"\$4000 .*? ↑↓ move r take recommended esc back")
        self.assertRegex(text, r"› recommended the cheapest as good: orch opus @ xhigh 97 \$4000 · "
                               r"builds astra @ xhigh 95 \$500 · reviews astra @ xhigh 96 \$500 .*? "
                               r"↑↓ move r take recommended esc back")
        self.assertIn("quality is a model's share of the best on the public boards, out of 100; "
                      "cost is what Artificial Analysis's index run cost it, in dollars", text)
        self.assertIn("› spark muse xhigh - - -", text)

    def test_a_line_taller_than_the_page_is_read_a_page_at_a_time(self):
        # seven more models as good to build and review: `as good` wraps past a page at 40
        # cells.  Up to the knob, then down through every row, and every line of the screen,
        # including the quality and cost note, is on some page drawn, even at 40x12
        self.store(matrix.scored([
            row("claude", "claude-opus-5-5", "max", 60, 70, 58, 8000, agent=0.2),
            row("claude", "claude-opus-5-5", "xhigh", 60, 70, 56, 4000),
            row("codex", "gpt-6-astra", "xhigh", 58, 66, 55, 500, agent=0.19),
            *[row("opencode", f"acme-model-{n}", "high", 58, 68, 56, 3000 + n, agent=0.19)
              for n in range(7)]]))
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
