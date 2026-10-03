"""ak never spends a usage-limit reset on its own; offline, with a fake Codex adapter.

Only the owner spends one, by hand (`usage.replenish`). A read of the meters, a worker refused
for quota and a seat refused for quota each leave the resets where they are, and a reset in
hand adds nothing to a provider's budget or headroom: one nobody spends is not usage ak can
run on. The count is still read, for the owner to spend from.
"""

import ast
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, usage

WEEK = 604800


def calls(path, name):
    """Every call to `name` in that file, as the function each sits in."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []

    def walk(node, inside):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, child.name)
                continue
            if isinstance(child, ast.Call):
                func = child.func
                called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if called == name:
                    found.append((inside, child))
            walk(child, inside)

    walk(tree, None)
    return found


class NothingSpendsAReset(unittest.TestCase):
    def test_only_replenish_asks_the_adapter_to_reset_and_no_loop_calls_it(self):
        # The adapter's `reset` verb is asked in one place, the owner's act ...
        askers = [(path.name, inside) for path in sorted((REPO / "agentkit").rglob("*.py"))
                  for inside, call in calls(path, "_adapter_json")
                  if len(call.args) > 1 and isinstance(call.args[1], ast.Constant)
                  and call.args[1].value == "reset"]
        self.assertEqual(askers, [("usage.py", "replenish")])
        # ... and nothing that reads meters, runs a worker or watches a seat calls it.
        for name in ("usage.py", "run.py", "watch.py", "job.py", "orch.py", "worker.py"):
            with self.subTest(module=name):
                self.assertEqual(calls(REPO / "agentkit" / name, "replenish"), [])
        for gone in ("_maybe_reset", "_reset_policy", "RESET_AT_USED", "RESET_EVERY_SECS",
                     "budget_from_resets"):
            self.assertFalse(hasattr(usage, gone), gone)

    def test_a_read_of_a_spent_week_with_resets_in_hand_spends_none(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        root = Path(stack.enter_context(tempfile.TemporaryDirectory(
            prefix=".ak-test-reset-never-", dir=REPO)))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {"HOME": str(root)}))
        config.ensure_dirs()
        cfg = config.load()
        cfg["providers"] = {"openai": cfg["providers"]["openai"]}
        cfg["models"] = {n: e for n, e in cfg["models"].items() if e["provider"] == "openai"}
        stack.enter_context(patch.object(usage, "_probe_every", return_value=0))
        used, asked = [95], []
        half = time.time() + WEEK / 2

        def adapter(argv, **_kw):
            verb = argv[-1]
            asked.append(verb)
            data = ({"meters": [{"name": "weekly", "used": used[0], "resets_at": half,
                                 "window_secs": WEEK}]} if verb == "usage"
                    else {"available": 2} if verb == "reset-status"
                    else {"code": "reset", "available": 1, "weekly_used": 0, "resets_at": half})
            return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")

        stack.enter_context(patch.object(usage.subprocess, "run", side_effect=adapter))
        for level in (95, 100):
            used[0] = level
            with self.subTest(used=level):
                for refresh in (False, True):
                    (config.STATE / "usage.json").unlink(missing_ok=True)
                    openai = usage.collect(cfg, refresh=refresh)["openai"]
                    usage.collect(cfg)                     # and again, from the warm cache
                self.assertNotIn("reset", asked)
                self.assertIn("reset-status", asked)   # the count is still read ...
                self.assertEqual(openai["resets"], 2)
                left = (100 - level) / 100
                # ... and adds nothing: headroom and budget are the week alone
                self.assertEqual(openai["headroom"], round(left, 3))
                self.assertAlmostEqual(openai["budget"], left / 0.5, delta=0.01)
                self.assertEqual(openai["exhausted"], level == 100)

    def test_a_reset_in_hand_adds_nothing_to_budget_or_headroom(self):
        now = 10000.0
        week = {"name": "weekly", "used": 60, "resets_at": now + WEEK / 2, "window_secs": WEEK}
        bare = {"meters": [week], "resets": 0, "error": None}
        for resets in (1, 3):
            held = {**bare, "resets": resets}
            self.assertEqual(usage.provider_budget(held, now), usage.provider_budget(bare, now))
            self.assertEqual(usage.provider_headroom(held, {}), 0.4)
            self.assertEqual(usage.outlook({**held, "meters": [usage._normalized(week, now)]}),
                             usage.outlook({**bare, "meters": [usage._normalized(week, now)]}))


if __name__ == "__main__":
    unittest.main()
