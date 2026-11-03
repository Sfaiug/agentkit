"""AK_BIN's models JSON measures the mean share of a provider's week per run and role.

Invented capacity pairs and launch receipts in a temporary HOME; no ledger token totals.
Missing pairs or diagnostics leave a role unknown rather than undercharging its task.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, boards

NOW = time.time()
ENDS = NOW + 86400


def pair(run, turn, model="anvil", effort="high", role="executor", tokens=1000, moved=1):
    return {"at": NOW - 100 + turn, "resets_at": ENDS, "tokens": tokens, "moved": moved,
            "run_id": run, "role": role, "model": model, "effort": effort}


class UsagePerTask(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fake = fakeadapter.install(home, claude="pass")["claude"]
        names = ("anvil", "bloom", "blank")
        fake.answer("models", "".join(f"{name}-1\t{name}\tlow high\n" for name in names))
        akconfig.write(home, {name: {"harness": "claude", "model": f"{name}-1",
                                   "effort": "high", "review_effort": "low"} for name in names})
        home.write(".agentkit/state/boards.json", boards())
        home.write(".agentkit/state/usage.json", {"providers": {"anthropic": {
            "provider": "anthropic", "probed_at": NOW, "error": None, "meters": [
                {"name": "weekly_all", "used": 40, "window_secs": 604800,
                 "resets_at": ENDS}]}}})

    def command(self):
        done = self.home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)

    def answer(self, *pairs):
        self.home.write(".agentkit/state/capacity.json",
                        {"anthropic": {"default": {"weekly_all": list(pairs)}}})
        for p in pairs:
            self.home.write(f'.agentkit/runs/{p["run_id"]}/round-1/'
                            f'{p["role"]}-{p["at"]}/harness', "claude")
        return self.command()

    def test_task_share_averages_runs_after_summing_all_rounds_in_the_role(self):
        answer = self.answer(pair("acme-short", 1), pair("acme-long", 2),
                             pair("acme-long", 3, tokens=3000, moved=2))
        self.assertEqual(answer["usage"]["anvil"]["high"], 800)
        self.assertEqual(answer["task_usage"]["anvil"]["high"],
                         {"executor": 2, "reviewer": None})

    def test_handoff_counts_for_neither_model_but_other_roles_and_runs_still_count(self):
        answer = self.answer(pair("acme-mixed", 1),
                             pair("acme-mixed", 2, "bloom", tokens=3000, moved=3),
                             pair("acme-mixed", 3, "bloom", "low", "reviewer", 2000),
                             pair("acme-clean", 4))
        found = answer["task_usage"]
        self.assertEqual(found["anvil"]["high"]["executor"], 1)
        self.assertIsNone(found["bloom"]["high"]["executor"])
        self.assertEqual(found["bloom"]["low"], {"executor": None, "reviewer": 1})

    def test_handoff_between_efforts_also_counts_for_neither(self):
        found = self.answer(pair("acme-mixed", 1), pair("acme-mixed", 2, effort="low"))
        self.assertEqual(found["task_usage"]["anvil"], {
            "high": {"executor": None, "reviewer": None},
            "low": {"executor": None, "reviewer": None}})

    def test_executor_and_reviewer_of_one_run_have_separate_shares(self):
        found = self.answer(pair("acme-run", 1),
                            pair("acme-run", 2, role="reviewer", tokens=3000, moved=3))
        self.assertEqual(found["task_usage"]["anvil"]["high"],
                         {"executor": 1, "reviewer": 3})

    def test_no_rate_or_no_qualifying_run_is_null(self):
        old = pair("acme-old", 1, "bloom")
        old.pop("role")
        self.home.write(".agentkit/state/capacity.json", {"anthropic": {"default": {
            "weekly_all": [old, pair("acme-zero", 2, moved=0)]}}})
        self.home.write(".agentkit/runs/acme-zero/round-1/executor/harness", "claude")
        found = self.command()
        self.assertIsNone(found["usage"]["anvil"]["high"])
        self.assertIsNotNone(found["usage"]["bloom"]["high"])
        self.assertEqual(found["task_usage"], {
            model: {effort: {"executor": None, "reviewer": None} for effort in rates}
            for model, rates in found["usage"].items()})

    def test_unpaired_launch_excludes_only_its_run_and_role(self):
        self.answer(pair("acme-partial", 1), pair("acme-partial", 2, role="reviewer"),
                    pair("acme-complete", 3, tokens=3000, moved=3))
        self.home.write(".agentkit/runs/acme-partial/round-2/executor/harness", "claude")
        self.assertEqual(self.command()["task_usage"]["anvil"]["high"],
                         {"executor": 3, "reviewer": 1})

    def test_a_task_without_launch_diagnostics_is_unknown(self):
        self.home.write(".agentkit/state/capacity.json", {"anthropic": {"default": {
            "weekly_all": [pair("acme-gone", 1)]}}})
        self.assertIsNone(self.command()["task_usage"]["anvil"]["high"]["executor"])

    def test_multiple_meter_pairs_count_one_turns_tokens_once(self):
        p = pair("acme-run", 1)
        self.answer(p)
        self.home.write(".agentkit/state/capacity.json", {"anthropic": {"default": {
            "weekly_all": [p], "weekly_scoped": [{**p, "moved": 10}]}}})
        self.assertEqual(self.command()["task_usage"]["anvil"]["high"]["executor"], 1)


if __name__ == "__main__":
    unittest.main()
