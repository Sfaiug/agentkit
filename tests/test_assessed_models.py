"""The recommendation is of the models the owner marks: `[assess]` in config.toml lists model
ids under each harness, and until it is written every model the config runs is assessed.
`ak models` lists and recommends among those alone, as does the line `c` says and `r` takes
(menu.advice); `rank` still orders every configured model.  An `[assess]` that is not model ids
per harness refuses the config.  The matrix is stored by hand, a throwaway HOME."""

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
from agentkit import config, matrix, menu, terminal


def row(harness, model, effort, name=None, **worth):
    return {"harness": harness, "model": model, "effort": effort, "name": name, "roles": [],
            "matched": {}, "values": {**scores.values(**worth), matrix.COST: 1}}


# the configured opus, and a model of a harness nobody configured, better and cheaper
TABLE = matrix.scored([row("claude", "claude-opus-5-5", "max", "opus", orchestrate=90,
                           execute=90, review=90),
                       row("acme", "acme-mini", None, execute=100, review=100)], scores.BEST)
TABLE[1]["values"][matrix.COST] = 0.1


class AssessedModels(Sandbox):
    def models(self):
        out = io.StringIO()
        with redirect_stdout(out), patch.object(config, "load", return_value=self.cfg), \
                patch.object(matrix, "refresh", return_value=({}, TABLE)), \
                patch.object(matrix, "live", return_value={}), \
                patch.object(terminal, "width", return_value=100):
            self.assertEqual(matrix.main([]), 0)
        return " ".join(terminal.plain(out.getvalue()).split())

    def test_until_a_mark_the_models_the_config_runs_are_assessed(self):
        self.assertEqual(matrix.assessed(self.cfg), {
            (entry["harness"], entry["model"]) for entry in self.cfg["models"].values()})
        text = self.models()
        self.assertIn("recommended: orchestrate opus @ max (90 of 2) · execute opus @ max (90 of 3) · "
                      "review opus @ max (90 of 3)", text)
        self.assertNotIn("acme-mini", text)
        self.assertEqual(menu.advice(self.cfg, {"rows": TABLE})["execute"],
                         ("opus @ max", "opus", "max"))

    def test_assess_in_the_config_marks_the_models_per_harness(self):
        self.cfg["assess"] = {"acme": ["acme-mini"]}
        self.assertEqual(matrix.assessed(self.cfg), {("acme", "acme-mini")})
        text = self.models()
        self.assertIn("recommended: execute acme-mini (100 of 3) · review acme-mini (100 of 3)", text)
        self.assertNotIn("opus", text)
        self.assertEqual(menu.advice(self.cfg, {"rows": TABLE})["execute"],
                         ("acme-mini", None, None))
        # written, the marks hold through a save; marking nothing assesses nothing
        config.save(self.cfg)
        self.assertEqual(config.load()["assess"], {"acme": ["acme-mini"]})
        self.cfg["assess"] = {}
        self.assertEqual(matrix.assessment(self.cfg, TABLE), [])
        self.assertIn("no recommendation yet: no board has a row ak can run", self.models())

    def test_an_assess_table_that_is_not_model_ids_per_harness_is_refused(self):
        path = config.HOME / config.CONFIG_NAME
        shipped = (REPO / config.DEFAULT_CONFIG_NAME).read_text()
        path.parent.mkdir(parents=True, exist_ok=True)
        for bad in ("assess = 3", '[assess]\nclaude = "claude-opus-5-5"', "[assess]\nclaude = [3]"):
            path.write_text(shipped.replace("\n[", f"\n{bad}\n\n[", 1))   # before the first table
            with self.assertRaisesRegex(config.Error, r"\[assess\] must list model ids under each harness"):
                config.load()


if __name__ == "__main__":
    unittest.main()
