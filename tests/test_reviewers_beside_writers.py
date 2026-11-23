"""A reviewer's pick given the work's writers leaves out every reviewer of a writer's lab while
one of another lab may review: with no lineup stored, as here, each provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."  `staffing.ready_order` narrows the list
before `usage.pick_order` reads it, so the pick is the one a run marked with only the reviewers
on other providers gets, so a subscription on the writer's provider keeps no payg reviewer on
another out.  22 Nov: "Own lab reviews when spent": a pick that comes back empty is made again,
at its own moment, without the writer's provider left out, a reviewer on another provider first.
A reviewer that is off, unready or barred, a list on the writer's provider alone, or a writer
the config does not know leaves the pick as it is without writers.

Offline: an invented config on two invented providers, fake meters, a throwaway HOME.
"""

from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import staffing, usage


def meters(**used):
    """Fake providers, each with one weekly meter `used` percent in."""
    return usage.Readings({name: {"meters": [{"name": "weekly", "used": pct, "pace": pct - 50,
                                              "elapsed": 50, "window_secs": 604800,
                                              "resets_at": time.time() + 302400}],
                                  "resets": 0} for name, pct in used.items()})


class ReviewersBesideWriters(Sandbox):
    def setUp(self):
        super().setUp()
        self.cfg = {"defaults": {"orchestrator": "opus", "workers": ["opus", "fable", "astra"]},
                    "models": {}, "providers": {"acme": {}, "beta": {}}}
        for name, provider in (("opus", "acme"), ("fable", "acme"), ("astra", "beta")):
            self.cfg["models"][name] = {"harness": "test", "model": f"{name}-1",
                                        "effort": "high", "provider": provider}
        # opus has more room than astra: without writers, it reviews first
        self.providers = meters(acme=10, beta=70)
        self.logs = []

    def pick(self, listed=("opus", "astra"), writers=None, log=None):
        return staffing.ready_order(self.cfg, self.providers, list(listed), log,
                                    writers=writers, role="reviewer", quiet=True)

    def test_a_reviewer_on_another_provider_alone_is_picked_and_the_log_says_why(self):
        self.assertEqual(self.pick(), ["opus", "astra"])
        self.assertEqual(self.pick(writers=["opus"], log=self.logs.append), ["astra"])
        self.assertEqual(self.logs,
                         ["skipped opus: a reviewer of another lab than opus is marked: astra"])

    def test_with_the_one_on_another_provider_spent_the_pick_is_made_again_without_writers(self):
        self.providers = meters(acme=10, beta=100)
        self.assertEqual(self.pick(["astra"]), [])
        self.assertEqual(self.pick(writers=["opus"], log=self.logs.append), self.pick())
        self.assertEqual(self.pick(), ["opus"])
        self.assertEqual(self.logs, [])     # opus is not left out of the pick returned

    def test_a_second_pick_holding_one_on_another_provider_names_it_first(self):
        # astra's refusal ends between the two picks: the sandbox's clock reads 10000
        self.providers["beta"]["exhausted_until"] = 10001
        pick_order, moments = usage.pick_order, iter((10000, 10002))

        def at_the_next_moment(*args, **kwargs):
            with patch.object(usage.time, "time", return_value=next(moments)):
                return pick_order(*args, **kwargs)

        with patch.object(usage, "pick_order", at_the_next_moment):
            self.assertEqual(self.pick(writers=["opus"]), ["astra", "opus"])

    def test_a_first_pick_naming_a_payg_one_on_another_provider_is_returned_as_it_is(self):
        self.cfg["providers"]["beta"]["mode"] = "payg"
        self.assertEqual(self.pick(), ["opus"])
        self.assertEqual(self.pick(writers=["opus"]), ["astra"])

    def test_one_off_unready_or_barred_leaves_the_pick_as_without_writers(self):
        def unchanged():
            self.assertEqual(self.pick(writers=["opus"]), self.pick())
            self.assertEqual(self.pick(), ["opus"])

        self.cfg["models_off"] = ["astra-1"]
        unchanged()
        del self.cfg["models_off"]
        self.cfg["models"]["astra"]["harness"] = "other"
        self.providers.harnesses = {"other": "other is not logged in"}
        unchanged()
        self.providers.harnesses = {}
        self.cfg["models"]["astra"]["harness"] = "grokbuild"    # loads the branch's AGENTS.md
        unchanged()

    def test_a_list_on_the_writers_provider_alone_is_left_as_it_is(self):
        self.assertEqual(self.pick(["opus", "fable"], ["opus"]), self.pick(["opus", "fable"]))
        self.assertEqual(self.pick(["opus", "fable"]), ["opus", "fable"])

    def test_a_writer_the_config_does_not_know_holds_nobody_back(self):
        self.assertEqual(self.pick(writers=["retired"]), self.pick())


if __name__ == "__main__":
    unittest.main()
