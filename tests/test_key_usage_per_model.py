"""AK_BIN's usage JSON measures the tokens a week holds from capacity pairs, which runs record.

Black-box, with a temporary HOME and invented capacity pairs. Overlaps share one login's
meter move; legacy pairs count too.
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

    def write(self, *pairs):
        self.home.write(".agentkit/state/capacity.json",
                        {"anthropic": {"default": {"weekly_all": list(pairs)}}})

    def holds(self):
        return self.command("usage", "--json")["providers"]["anthropic"]["capacity_tokens"]

    def test_overlapping_turns_split_the_same_one_percent_by_tokens(self):
        self.write(pair("anvil", prior=40), pair("bloom", tokens=3000, prior=40))
        self.assertEqual(self.holds(), 400000)

    def test_partial_overlaps_share_only_the_part_both_claim(self):
        self.write(pair("anvil", prior=40, moved=2), pair("bloom", tokens=3000, prior=41, moved=2))
        self.assertEqual(self.holds(), 133333)

    def test_the_same_percent_in_different_windows_counts_twice(self):
        self.write(pair("anvil", prior=40, ends=ENDS - WEEK), pair("bloom", tokens=3000, prior=40))
        self.assertEqual(self.holds(), 200000)

    def test_legacy_pairs_count_toward_holds(self):
        old = {"at": NOW - 200, "tokens": 10000, "moved": 2, "resets_at": ENDS}
        self.write(old, pair("anvil"))
        self.assertEqual(self.holds(), 366667)

    def test_new_pairs_record_the_turns_model_effort_run_and_role(self):
        rig = Rig(self.home, "widgets", files={"AGENTS.md": "---\nhealth: none\ntests: true\n---\n"})
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
