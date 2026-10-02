"""At handover, ready reviewers from providers that refused nothing go first.

Offline: invented models and meters, a temporary HOME, no worker or adapter calls.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run


class RefusedReviewsLast(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-refused-reviews-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"HOME": tmp.name}))
        self.stack.enter_context(patch.object(config, "HOME", Path(tmp.name)))
        self.stack.enter_context(patch.object(config, "active_session", return_value=None))
        self.cfg = {"defaults": {"workers": ["acme-build", "beta-build"]},
                    "models": {}, "providers": {"acme": {}, "beta": {}, "gamma": {}}}
        for name, provider in (("acme-build", "acme"), ("acme-review", "acme"),
                               ("beta-build", "beta"), ("beta-review", "beta"),
                               ("gamma-review", "gamma")):
            self.cfg["models"][name] = {"harness": "test", "model": name,
                                        "effort": "high", "provider": provider}
        self.providers = {
            name: {"meters": [{"name": "weekly", "used": used, "pace": used - 50,
                               "elapsed": 50, "window_secs": 604800,
                               "resets_at": time.time() + 302400}], "resets": 0}
            for name, used in (("acme", 10), ("beta", 40), ("gamma", 70))}
        self.stack.enter_context(patch.object(run, "collect_usage", return_value=self.providers))

    def handover(self, reviewers, dry=()):
        state = {"executor": "acme-build", "reviewer": "acme-review",
                 "exec_session": "saved-executor", "review_session": "saved-review",
                 "workers": ["acme-build", "beta-build"], "reviewers": reviewers}
        self.assertEqual(run.handover_executor(state, self.cfg, "stalled", dry=dry),
                         "beta-build")
        self.assertIsNone(state["exec_session"])
        self.assertEqual(state["executor_history"][0]["from"], "acme-build")
        self.assertEqual(state["executor_history"][0]["to"], "beta-build")
        return state

    def test_ready_provider_beats_refused_reviewers_better_budget(self):
        state = self.handover(["acme-review", "gamma-review"])
        self.assertEqual(state["reviewer"], "gamma-review")
        self.assertIsNone(state["review_session"])

    def test_ready_provider_beats_refused_reviewers_better_tier(self):
        for reviewer in ("beta-review", "beta-build"):
            with self.subTest(reviewer=reviewer):
                state = self.handover(["acme-review", reviewer])
                self.assertEqual(state["reviewer"], reviewer)

    def test_previous_refusals_also_put_their_reviewers_last(self):
        state = self.handover(["gamma-review", "beta-review"], dry=("gamma",))
        self.assertEqual(state["reviewer"], "beta-review")

    def test_only_refused_provider_ready_still_reviews(self):
        self.providers["gamma"]["meters"][0]["used"] = 100
        for reviewer in ("acme-review", "acme-build"):
            with self.subTest(reviewer=reviewer):
                state = self.handover([reviewer, "gamma-review"])
                self.assertEqual(state["reviewer"], reviewer)

    def test_later_pick_uses_normal_order(self):
        state = self.handover(["acme-review", "gamma-review"])
        self.assertEqual(state["reviewer"], "gamma-review")
        self.assertEqual(run.pick_models(self.cfg, self.providers, state["executor"], None,
                                         lambda _: None, workers=state["workers"],
                                         reviewers=state["reviewers"]),
                         ("beta-build", "acme-review"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
