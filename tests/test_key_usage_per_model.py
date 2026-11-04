"""AK_BIN's models JSON measures weekly percentage points per million tokens.

Black-box, with a temporary HOME and invented capacity pairs. Overlaps share one login's
meter move; accounts pool rates, never meter coordinates. Legacy pairs only measure holds.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig
from test_key_models_answer import ENV, boards

NOW = time.time()
WEEK = 604800
ENDS = NOW + 86400


def pair(model, effort="high", tokens=1000, prior=10, moved=1, ends=ENDS):
    return {"at": min(NOW - 100, ends - 60), "resets_at": ends, "tokens": tokens,
            "prior": prior, "moved": moved, "model": model, "effort": effort,
            "run_id": "acme-run", "role": "executor"}


class UsagePerModel(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.fake = fakeadapter.install(home, claude="pass")["claude"]
        names = ("anvil", "bloom", "blank")
        self.fake.answer("models", "".join(f"{name}-1\t{name}\tlow high\n" for name in names))
        akconfig.write(home, {name: {"harness": "claude", "model": f"{name}-1",
                                   "effort": "high", "review_effort": "low"} for name in names},
                       workers=["anvil"], reviewers=["bloom"])
        home.write(".agentkit/state/boards.json", boards())
        home.write(".agentkit/state/usage.json", {"providers": {"anthropic": {
            "provider": "anthropic", "probed_at": NOW, "error": None, "meters": [
                {"name": "weekly_all", "used": 40, "window_secs": WEEK, "resets_at": ENDS}]}}})

    def command(self, *args):
        done = self.home.ak(*args, env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)

    def answer(self, *pairs):
        self.home.write(".agentkit/state/capacity.json",
                        {"anthropic": {"default": {"weekly_all": list(pairs)}}})
        return self.command("models", "--json")["usage"]

    def holds(self):
        return self.command("usage", "--json")["providers"]["anthropic"]["capacity_tokens"]

    def test_each_model_and_effort_uses_its_own_rate_including_zero_move_tokens(self):
        answer = self.answer(pair("anvil"), pair("anvil", prior=11, moved=0),
                             pair("anvil", "low", tokens=4000, prior=11),
                             pair("bloom", prior=12, moved=4))
        self.assertEqual(answer["anvil"], {"high": 500, "low": 250})
        self.assertEqual(answer["bloom"], {"high": 4000, "low": None})

    def test_overlapping_turns_split_the_same_one_percent_by_tokens(self):
        answer = self.answer(pair("anvil", prior=40),
                             pair("bloom", tokens=3000, prior=40))
        self.assertEqual(answer["anvil"]["high"], 250)
        self.assertEqual(answer["bloom"]["high"], 250)
        self.assertEqual(self.holds(), 400000)

    def test_partial_overlaps_share_only_the_part_both_claim(self):
        answer = self.answer(pair("anvil", prior=40, moved=2),
                             pair("bloom", tokens=3000, prior=41, moved=2))
        self.assertEqual(answer["anvil"]["high"], 1250)
        self.assertAlmostEqual(answer["bloom"]["high"], 1e6 * 1.75 / 3000)
        self.assertEqual(self.holds(), 133333)

    def test_the_same_percent_in_different_windows_counts_twice(self):
        answer = self.answer(pair("anvil", prior=40, ends=ENDS - WEEK),
                             pair("bloom", tokens=3000, prior=40))
        self.assertEqual(answer["anvil"]["high"], 1000)
        self.assertAlmostEqual(answer["bloom"]["high"], 1e6 / 3000)
        self.assertEqual(self.holds(), 200000)

    def test_no_pairs_and_zero_moves_report_null_without_borrowing_an_effort(self):
        answer = self.answer(pair("anvil", moved=0), pair("anvil", "low"))
        self.assertEqual(answer, {"anvil": {"high": None, "low": 1000},
                                  "bloom": {"high": None, "low": None},
                                  "blank": {"high": None, "low": None}})

    def test_legacy_pairs_count_toward_holds_and_toward_no_model(self):
        old = {"at": NOW - 200, "tokens": 10000, "moved": 2, "resets_at": ENDS}
        answer = self.answer(old, pair("anvil"))
        self.assertEqual(answer["anvil"]["high"], 1000)
        self.assertIsNone(answer["bloom"]["high"])
        self.assertEqual(self.holds(), 366667)

    def test_provider_pools_models_by_tokens_without_merging_logins_moves(self):
        cfg = akconfig.read(self.home)
        akconfig.write(self.home, cfg["models"], providers={"anthropic": {
            **cfg["providers"]["anthropic"], "accounts": ["default", "second"]}})
        path = self.home.path / ".agentkit/state/usage.json"
        record = json.loads(path.read_text())["providers"]["anthropic"]
        self.home.write(".agentkit/state/usage.json", {"providers": {"anthropic": {
            "provider": "anthropic", "accounts": dict.fromkeys(("default", "second"), record)}}})
        self.home.write(".agentkit/state/capacity.json", {"anthropic": {
            "default": {"weekly_all": [pair("anvil"), pair("bloom", tokens=3000)]},
            "second": {"weekly_all": [pair("anvil"), pair("bloom")]}}})
        answer = self.command("models", "--json")["usage"]
        self.assertEqual(answer["anvil"]["high"], 375)
        self.assertEqual(answer["bloom"]["high"], 312.5)

    def test_pairs_older_than_the_previous_meter_window_count_for_nothing(self):
        path = self.home.path / ".agentkit/state/usage.json"
        held = json.loads(path.read_text())
        held["providers"]["anthropic"]["meters"][0]["resets_at"] += 2 * WEEK
        path.write_text(json.dumps(held))
        self.assertIsNone(self.answer(pair("anvil"))["anvil"]["high"])

    def test_capacity_pairs_need_no_live_meter_reading(self):
        (self.home.path / ".agentkit/state/usage.json").unlink()
        self.assertEqual(self.answer(pair("anvil"))["anvil"]["high"], 1000)

    def test_observed_efforts_remain_measured_after_the_configured_effort_changes(self):
        self.assertEqual(self.answer(pair("anvil", "medium"))["anvil"],
                         {"high": None, "low": None, "medium": 1000})

    def test_a_models_scoped_meter_is_not_its_providers_week(self):
        cfg = akconfig.read(self.home)
        cfg["models"]["bloom"]["meter"] = "weekly_scoped"
        akconfig.write(self.home, cfg["models"])
        (self.home.path / ".agentkit/state/usage.json").unlink()
        self.home.write(".agentkit/state/capacity.json", {"anthropic": {"default": {
            "weekly_all": [pair("bloom")], "weekly_scoped": [pair("bloom", moved=10)]}}})
        self.assertEqual(self.command("models", "--json")["usage"]["bloom"]["high"], 1000)

    def test_retained_unoffered_models_do_not_break_the_answer(self):
        with (self.home.path / ".agentkit/config.toml").open("a") as opened:
            opened.write('\n[models.unfinished]\nharness = "claude"\nmodel = "unused-1"\n')
        answer = self.answer(pair("unfinished"))
        self.assertEqual(set(answer), {"anvil", "bloom", "blank"})
        self.assertIsNone(answer["anvil"]["high"])

    def test_new_pairs_record_the_turns_model_effort_run_and_role(self):
        rig = Rig(self.home, "widgets", files={"AGENTS.md": "---\ntests: true\n---\n"})
        events = "".join(json.dumps(event) + "\n" for event in [
            {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed",
             "unifiedWindows": {"seven_day": {"utilization": .41, "resetsAt": ENDS}}}},
            {"type": "result", "usage": {"input_tokens": 1000, "output_tokens": 0}}])
        self.fake.behave({**fakeadapter.WORK, "events": events},
                         {**fakeadapter.PASS, "events": events})
        done = self.home.ak("run", str(taskfile.write(self.home, rig.path)), "--no-merge",
                            env=ENV, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run = taskfile.only_run(self.home)
        saved = json.loads((self.home.path / ".agentkit/state/capacity.json").read_text())
        pairs = saved["anthropic"]["default"]["weekly_all"]
        self.assertEqual([(p["model"], p["effort"], p["run_id"], p["role"]) for p in pairs],
                         [("anvil", "high", run.name, "executor"),
                          ("bloom", "low", run.name, "reviewer")])
        self.assertEqual([(p["tokens"], p["prior"], p["moved"]) for p in pairs],
                         [(1000, 40, 1), (1000, 41, 0)])


if __name__ == "__main__":
    unittest.main()
