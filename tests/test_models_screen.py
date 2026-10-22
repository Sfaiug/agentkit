"""The models screen, `r recommended` on `c`: the matrix is computed as it opens, the rule
gliding and the roles empty until the boards land, then a line per role with the recommended
row, its quality, what a task of Artificial Analysis's index run cost it and how many more rows
are as good; the one knob, `within`, stepped by ←/→ and saved at once, the recommendation
following; and every model the harnesses offer under its harness, two columns where the width
holds them, each with a mark: space flips it, saved to config.toml as `[assess]` at once, and
the recommendation follows; `r` takes the recommendation.  The matrix is stored by hand, the
boards' reading faked, a throwaway HOME."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import threading
import time
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

READ_AT = time.mktime((2026, 10, 20, 13, 4, 0, 0, 0, -1))
BOARDS = {"arena.ai": {"fetched_at": READ_AT}, "livebench.ai": {"fetched_at": READ_AT + 60}}


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
        self.cfg["models"]["grok-4.6"] = {**self.cfg["models"]["grok"], "model": "grok-4.6"}
        config.save(self.cfg)         # an entry named after its id
        self.stack.enter_context(patch.object(update, "agentkit_version", return_value="abc1234"))
        self.stack.enter_context(patch.object(usage, "collect", return_value=usage.Readings({})))
        self.stack.enter_context(patch.object(terminal, "layout_width", return_value=100))
        self.stack.enter_context(patch.dict("os.environ", {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        # the screen reads the boards as it opens: here the stored rows, once `landed` is set
        self.landed = threading.Event()
        self.landed.set()
        self.stack.enter_context(patch.object(matrix, "refresh", side_effect=self.refresh))
        case, fetches = self, []

        class Fetch(menu.Fetch):      # the reading, for the keys to wait on its landing
            def __init__(self, work):
                super().__init__(work)
                fetches.append(self)
        self.stack.enter_context(patch.object(menu, "Fetch", Fetch))
        self.fetches = fetches
        # opus at three efforts; astra as good as its xhigh at an eighth of the cost; sonnet,
        # not configured, under the best by more; mimo, which the boards list naming no effort,
        # one row at none; spark, which no board has
        scores.store([row("claude", "claude-opus-5-5", "max", 100, 100, 100, cost=8),
                      row("claude", "claude-opus-5-5", "xhigh", 96.55, 96.55, 96.55, cost=4),
                      row("claude", "claude-opus-5-5", "high", 86.2, 86.2, 86.2, cost=2),
                      row("codex", "gpt-6-astra", "xhigh", 84.64, 95.48, 95.75, cost=0.5),
                      row("claude", "claude-sonnet-5-5", "max", 67.86, 84.52, 84.77, cost=7),
                      row("opencode", "mimo-pro", None, None, 50.71, 50.86, cost=0.1),
                      row("muse", "muse-spark-1.3-contributor", None),
                      row("grokbuild", "grok-4.6", None)])

    def refresh(self, cfg, **_kw):
        self.landed.wait(10)
        return BOARDS, matrix.stored().get("rows") or []

    def keys(self, *rest, landed=True):
        """`r` on `c`, then, once the boards have landed (`landed`), a resize and `rest`."""
        yield Key("char", "r")
        if landed:
            self.landed.set()
        self.fetches[-1].join(10)
        yield Key("resize")
        yield from rest

    def lines(self, keys, width=100):
        """Every line drawn while `c` is driven by `keys` on a screen `width` wide, in order,
        each its words one space apart and without its highlight mark; a screen draws again
        only the lines that changed."""
        drawn = io.StringIO()
        with patch.object(terminal, "read_key", side_effect=keys), redirect_stdout(drawn), \
                patch.object(terminal, "layout_width", return_value=width):
            menu.show_config(False, Keyboard(), "fix-api")
        lines = [terminal.plain(line, spaced=True) for line in drawn.getvalue().splitlines()]
        self.assertEqual([line for line in lines if terminal.cells(line) > width], [],
                         "a line runs past the screen")
        return [" ".join(line.removeprefix("›").split()) for line in lines if line.strip()]

    def screens(self, keys, width=100):
        return " ".join(self.lines(keys, width))


KNOB = "as good within ‹ 5 › points of the best; the cheapest of those wins"


class ModelsScreen(Screen):
    def setUp(self):
        super().setUp()
        # each configured model as the screen names it, in full (config.model_name)
        self.opus, self.astra, self.grok = (config.model_name(self.cfg, name)
                                            for name in ("opus", "astra", "grok-4.6"))
        # one row per model as good: opus at its cheapest effort as good, max, counts once
        self.picks = [f"orch {self.opus} @ xhigh 97 $4.00 a task",
                      f"builds {self.astra} @ xhigh 95 $0.50 a task 1 more as good",
                      f"reviews {self.astra} @ xhigh 96 $0.50 a task 1 more as good"]

    def test_r_on_c_opens_the_screen_with_the_picks_the_knob_and_every_model_marked_or_not(self):
        lines = self.lines(self.keys(Key("esc"), Key("esc")))
        self.assertIn("agentkit · models · fix-api", " ".join(lines))
        self.assertEqual(lines[lines.index(self.picks[0]):][:3], self.picks)
        self.assertIn(KNOB, lines)
        # every model under its harness, two columns wide, the configured ones marked and
        # named in full, the id after: claude and codex down the left, opencode and muse the
        # right; spark, whose full name is its id, says it once
        self.assertEqual(lines[lines.index("claude opencode"):][:6],
                         ["claude opencode", f"■ {self.opus} claude-opus-5-5 □ mimo-pro",
                          "□ claude-sonnet-5-5 muse", "codex ■ muse-spark-1.3-contributor",
                          f"■ {self.astra} gpt-6-astra grokbuild", f"■ {self.grok} grok-4.6"])
        self.assertIn("4 of 6 marked · boards read 20 Oct 13:04", lines)
        self.assertIn("↑↓ move r take recommended esc back", lines)

    def test_the_roles_wait_for_the_boards_and_the_rule_glides_meanwhile(self):
        self.landed.clear()

        def keys():
            yield Key("char", "r")
            yield Key("resize")       # drawn again while the boards are read
            self.landed.set()         # the boards land while the screen is up
            self.fetches[-1].join(10)
            yield Key("resize")
            yield Key("esc")
            yield Key("esc")
        lines = self.lines(keys())
        opened = lines.index(next(line for line in lines if "models · fix-api" in line))
        landed = lines.index(self.picks[0])
        self.assertLess(opened, landed)
        self.assertEqual(list(dict.fromkeys(line for line in lines[opened:landed]
                                            if line.startswith(("orch", "builds", "reviews",
                                                                "as good", "0 of")))),
                         ["orch", "builds", "reviews", KNOB, "0 of 0 marked · reading the boards"])
        self.assertEqual(lines[landed:landed + 3], self.picks)

    def test_a_long_id_after_a_name_gives_way_and_the_columns_stay_two(self):
        # a configured model whose full name and id together fill more than half the screen
        long_id = "acme/acme-5-preview-with-a-long-tail"
        self.cfg["models"]["preview"] = {**self.cfg["models"]["opus"], "model": long_id}
        config.save(self.cfg)
        scores.store([*matrix.stored()["rows"], row("claude", long_id, "max", 50, 50, 50, cost=1)])
        lines = self.lines(self.keys(Key("esc"), Key("esc")))
        self.assertIn("claude opencode", lines)
        self.assertTrue(any(line.startswith("■ acme-5-preview-with-a-long-tail acme/")
                            and "…" in line for line in lines), lines)

    def test_space_marks_a_model_saved_at_once_and_the_recommendation_follows(self):
        # one column at 40 cells: the roles, the knob, then opus, sonnet, astra, mimo, spark, grok-4.6
        down = [Key("down")] * 5
        text = self.screens(self.keys(*down, Key("char", " "), Key("esc"), Key("esc")), width=40)
        self.assertIn("■ claude-sonnet-5-5", text)
        self.assertIn(f"claude ■ {self.opus} claude-opus-5-5 ■ claude-sonnet-5-5 codex", text)
        self.assertEqual(matrix.assessed(config.load()),
                         matrix.assessed(self.cfg) | {("claude", "claude-sonnet-5-5")})
        # unmarked again, and opus too: without it astra is the best in every role
        text = self.screens(self.keys(*down, Key("char", " "), Key("up"), Key("char", " "),
                                      Key("esc"), Key("esc")), width=40)
        self.assertEqual(matrix.assessed(config.load()),
                         matrix.assessed(self.cfg) - {("claude", "claude-opus-5-5")})
        # the narrow screen holds neither the cost nor the rows as good
        astra = self.astra
        self.assertIn(f"orch {astra} @ xhigh 85 builds {astra} @ xhigh 95 reviews {astra} @ xhigh "
                      "96", text)
        self.assertIn(f"□ {self.opus} claude-opus-5-5", text)
        self.assertIn("↑↓←→ move space mark r take recommended esc back", text)

    def test_space_marks_the_model_the_pointer_is_on_even_past_its_name(self):
        # screen row 9 holds opus on the left and mimo-pro on the right, its name ending short of 75
        self.screens(self.keys(Key("point", "", 75, 9), Key("char", " "), Key("esc"), Key("esc")))
        self.assertEqual(matrix.assessed(config.load()),
                         matrix.assessed(self.cfg) | {("opencode", "mimo-pro")})

    def test_a_resize_to_two_columns_keeps_the_highlight_on_its_model(self):
        def keys():   # one column at 40 cells, grok-4.6 last, on a line two columns do not have
            yield from self.keys(*[Key("down")] * 9)
            terminal.layout_width.return_value = 100
            yield from (Key("resize"), Key("char", " "), Key("esc"), Key("esc"))
        with patch.object(terminal, "read_key", side_effect=keys()), redirect_stdout(io.StringIO()), \
                patch.object(terminal, "layout_width", return_value=40):
            menu.show_config(False, Keyboard(), "fix-api")
        self.assertEqual(matrix.assessed(config.load()),
                         matrix.assessed(self.cfg) - {("grokbuild", "grok-4.6")})

    def test_a_resize_to_one_column_draws_the_highlight_on_its_model(self):
        drawn, narrowed = io.StringIO(), []

        def keys():   # mimo-pro, on the right of opus at 100 cells, then 40: under spark's harness
            yield from self.keys(*[Key("down")] * 4, Key("right"))
            terminal.layout_width.return_value = 40
            narrowed.append(drawn.tell())
            yield from (Key("resize"), Key("char", " "), Key("esc"), Key("esc"))
        with patch.object(terminal, "read_key", side_effect=keys()), redirect_stdout(drawn), \
                patch.object(terminal, "layout_width", return_value=100):
            menu.show_config(False, Keyboard(), "fix-api")
        lit = [line for line in map(terminal.plain, drawn.getvalue()[narrowed[0]:].splitlines())
               if line.startswith("›")]
        self.assertTrue(lit and "mimo-pro" in lit[0], lit)
        self.assertEqual(matrix.assessed(config.load()),
                         matrix.assessed(self.cfg) | {("opencode", "mimo-pro")})

    def test_a_long_recommended_name_is_cut_to_a_phone(self):
        long_id = "acme/" + "long-model-name-" * 4
        self.cfg["models"]["opus"]["model"] = long_id
        config.save(self.cfg)
        scores.store([row("claude", long_id, "max", 100, 100, 100, cost=1)])
        lines = self.lines(self.keys(Key("esc"), Key("esc")), width=40)   # none past the screen
        self.assertTrue(any(line.startswith("orch long-model-name-") and "…" in line
                            for line in lines), lines)

    def test_the_knob_steps_within_saved_at_once_and_the_recommendation_follows(self):
        lines = self.lines(self.keys(*[Key("down")] * 3, Key("left"), Key("esc"), Key("esc")))
        self.assertIn("as good within ‹ 4 › points of the best; the cheapest of those wins", lines)
        self.assertEqual(config.load()["within"], 4)
        # astra, 4.52 under the best to build and 4.25 to review, is no longer as good
        self.assertIn(f"builds {self.opus} @ xhigh 97 $4.00 a task", lines)
        self.assertIn(f"reviews {self.opus} @ xhigh 97 $4.00 a task", lines)
        self.assertIn("↑↓ move ←→ as good r take recommended esc back", lines)

    def test_r_on_the_screen_takes_the_recommendation(self):
        self.screens(self.keys(Key("char", "r"), Key("esc"), Key("esc")))
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual((record["orchestrator"], record["workers"], record["reviewers"]),
                         ("opus", ["astra"], ["astra"]))
        astra = config.load()["models"]["astra"]       # the rows at its own effort: it follows
        self.assertEqual((astra["effort"], astra.get("exec_effort"), astra.get("review_effort")),
                         ("xhigh", None, None))


if __name__ == "__main__":
    unittest.main()
