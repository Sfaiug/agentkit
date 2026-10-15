"""A reviewer from the writer's own company counts as any other; only the writer's own model
comes last.

The owner's decision of 14 Oct (AGENTS.md, Owner rules): a stronger reviewer catches more than
a different company does, and the reviewer's separate turn already gives the fresh context.  So
the reviewer order is the budget order among every other model, the writer's own model after
them, and the pair every automatic pick takes weighs only own-model against other; `ak usage`
no longer remarks on a reviewer from the executor's company.

Offline: invented models on two invented providers, fake meters, no adapter or model call.
"""

from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, staffing, terminal, usage

CFG = {"defaults": {"orchestrator": "acme-one", "workers": ["acme-one", "acme-two", "beta-one"]},
       "models": {name: {"harness": "test", "model": name, "effort": "high", "provider": provider}
                  for name, provider in (("acme-one", "acme"), ("acme-two", "acme"),
                                         ("beta-one", "beta"))},
       "providers": {"acme": {}, "beta": {}}}


def meters(acme, beta):
    return {name: {"meters": [{"name": "weekly", "used": used, "pace": used - 50, "elapsed": 50,
                               "window_secs": 604800, "resets_at": time.time() + 302400}],
                   "resets": 0} for name, used in (("acme", acme), ("beta", beta))}


class SameCompanyReview(unittest.TestCase):
    def test_the_reviewer_order_keeps_budget_order_among_every_other_model(self):
        self.assertEqual(staffing.reviewer_order(CFG, "acme-one", ["acme-two", "beta-one", "acme-one"]),
                         ["acme-two", "beta-one", "acme-one"])
        self.assertEqual(staffing.reviewer_order(CFG, ["acme-one", "beta-one"],
                                                 ["acme-two", "beta-one", "acme-one"]),
                         ["acme-two", "beta-one", "acme-one"])
        self.assertEqual(staffing.pair_tier(CFG, "acme-one", "acme-two"), 0)
        self.assertEqual(staffing.pair_tier(CFG, "acme-one", "beta-one"), 0)
        self.assertEqual(staffing.pair_tier(CFG, "acme-one", "acme-one"), 2)
        self.assertEqual(staffing.best_pair(CFG, ["acme-one", "beta-one"], ["acme-two", "beta-one"]),
                         ("acme-one", "acme-two"))

    def test_a_same_company_reviewer_with_more_budget_is_picked_and_not_remarked_on(self):
        providers = meters(acme=10, beta=70)
        with patch.object(config, "active_session", return_value=None), \
                patch.object(usage, "readiness", side_effect=lambda cfg, read: read):
            self.assertEqual(staffing.pick_models(CFG, providers, None, None, lambda _: None),
                             ("acme-one", "acme-two"))
            self.assertEqual(usage.review_pair(CFG, providers),
                             {"executor": "acme-one", "reviewer": "acme-two", "self_reviewed": False})
            with patch.object(terminal, "width", return_value=120):
                text = usage.render(CFG, providers, ["acme-one", "acme-two", "beta-one"])
        self.assertIn("review: acme-one by acme-two", text)
        self.assertNotIn("one provider", text)


if __name__ == "__main__":
    unittest.main()
