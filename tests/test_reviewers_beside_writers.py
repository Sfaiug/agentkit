"""A reviewer's pick given the work's writers leaves out every reviewer of a writer's lab while
one of another lab may review: with no lineup stored, as here, each provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."  `staffing.ready_order` narrows the list
before `usage.pick_order` reads it, so the pick is the one a run marked with only the reviewers
on other providers gets, so a subscription on the writer's provider keeps no payg reviewer on
another out.  22 Nov: "Own lab reviews when spent": a pick that comes back empty is made again
of the reviewers it left out alone, so it never names one on another provider.  A reviewer that
is off, unready or barred, a list on the writer's provider alone, or a writer the config does
not know leaves the pick as it is without writers.  An executor's pick given the run's reviewers
leaves out the same way every executor no reviewer on another provider can review, and is made
again the same way; a handover's is made again too where every executor it keeps is on a
provider that refused the work (`staffing.next_executor`).

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
        return staffing.ready_order(self.cfg, self.providers, listed and list(listed), log,
                                    writers=writers, role="reviewer", quiet=True)

    def test_a_reviewer_on_another_provider_alone_is_picked_and_the_log_says_why(self):
        self.assertEqual(self.pick(), ["opus", "astra"])
        self.assertEqual(self.pick(writers=["opus"], log=self.logs.append), ["astra"])
        self.assertEqual(self.logs,
                         ["skipped opus: a reviewer of another lab than opus is marked: astra"])

    def test_with_the_one_on_another_provider_spent_those_on_the_writers_review(self):
        self.providers = meters(acme=10, beta=100)
        self.assertEqual(self.pick(["astra"]), [])
        self.assertEqual(self.pick(None, ["opus"], self.logs.append), ["opus", "fable"])
        self.assertEqual(self.logs, [])     # neither is left out of the pick returned

    def at_two_moments(self, listed):
        """The pick of `listed` beside opus with astra refused until 10001, and how many picks
        `pick_order` made: the first read at the sandbox's 10000, the second at 10002."""
        self.providers["beta"]["exhausted_until"] = 10001
        pick_order, read = usage.pick_order, []

        def at_the_next_moment(*args, **kwargs):
            read.append((10000, 10002)[len(read)])
            with patch.object(usage.time, "time", return_value=read[-1]):
                return pick_order(*args, **kwargs)

        with patch.object(usage, "pick_order", at_the_next_moment):
            return self.pick(listed, ["opus"]), len(read)

    def test_one_on_another_provider_back_between_the_picks_is_not_in_the_second(self):
        self.assertEqual(self.at_two_moments(["opus", "astra"]), (["opus"], 2))

    def test_an_empty_pick_the_rule_left_nobody_out_of_is_not_made_again(self):
        self.assertEqual(self.at_two_moments(["astra"]), ([], 1))

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

    def test_an_executors_pick_with_the_one_another_provider_reviews_spent_builds_on_opus(self):
        def executors():
            return staffing.ready_order(self.cfg, self.providers, ["opus", "astra"],
                                        self.logs.append, reviewed_by=["opus"], quiet=True)

        self.assertEqual(executors(), ["astra"])
        self.assertEqual(self.logs,
                         ["skipped opus: a marked reviewer of another lab can review astra"])
        self.logs.clear()
        self.providers = meters(acme=10, beta=100)
        self.assertEqual((executors(), self.logs), (["opus"], []))

    def test_a_handover_whose_kept_executors_provider_refused_it_builds_on_opus(self):
        def handed(dry):
            return staffing.next_executor(self.cfg, self.providers, dry, "opus", self.logs.append,
                                          workers=["opus", "astra"], reviewers=["opus"])

        self.assertEqual(handed(set()), ("astra", "opus"))
        self.assertEqual(self.logs,
                         ["skipped opus: a marked reviewer of another lab can review astra"])
        self.logs.clear()
        self.assertEqual((handed({"beta"}), self.logs), (("opus", "opus"), []))

    def test_a_refused_subscription_keeps_no_payg_one_out_of_the_handover_made_again(self):
        self.cfg["providers"]["acme"]["mode"] = "payg"
        self.providers = meters(acme=10, beta=10)
        self.assertEqual(staffing.next_executor(self.cfg, self.providers, {"beta"}, "opus", None,
                                                workers=["astra", "opus"], reviewers=["opus"]),
                         ("opus", "opus"))


if __name__ == "__main__":
    unittest.main()
