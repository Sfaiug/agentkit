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
again the same way.  A handover's picks of both roles read nobody on a provider that refused
the work (`staffing.next_executor`), so a refused subscription keeps no payg one out of either,
and a resume's leaves out the executor it skips before the rule reads the list
(`staffing.resume_models`).  A launch whose pick is still empty waits without claiming a full
meter it never read.

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
from agentkit import config, staffing, turns, usage


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

    def test_a_launch_both_providers_refused_waits_without_claiming_a_full_meter(self):
        self.providers = meters(acme=10, beta=10)
        for provider in ("acme", "beta"):
            self.providers[provider]["exhausted_until"] = 20000
        with self.assertRaises(turns.QuotaDry) as caught:
            staffing.pick_models(self.cfg, self.providers, None, None, self.logs.append,
                                 quiet=True, workers=["opus", "astra"], reviewers=["opus"])
        self.assertNotIn("100%", str(caught.exception))

    def test_a_resume_skipping_the_one_another_provider_reviews_builds_on_opus(self):
        self.providers = meters(acme=10, beta=10)
        state = {"step": "executor", "executor": "astra", "reviewer": "opus",
                 "workers": ["astra", "opus"], "reviewers": ["opus"]}
        self.assertEqual(staffing.resume_models(self.cfg, self.providers, state),
                         ("astra", "opus"))
        self.assertEqual(staffing.resume_models(self.cfg, self.providers, state, skip=("astra",)),
                         ("opus", "opus"))

    def test_a_refused_subscription_keeps_no_payg_one_out_of_the_handover_made_again(self):
        self.cfg["providers"]["acme"]["mode"] = "payg"
        self.providers = meters(acme=10, beta=10)
        self.assertEqual(staffing.next_executor(self.cfg, self.providers, {"beta"}, "opus", None,
                                                workers=["astra", "opus"], reviewers=["opus"]),
                         ("opus", "opus"))

    def test_a_refused_subscription_keeps_no_payg_reviewer_out_of_the_handover(self):
        self.cfg["models"]["opus"]["mode"] = "payg"
        self.providers = meters(acme=10, beta=10)
        self.assertEqual(staffing.next_executor(self.cfg, self.providers, {"beta"}, "astra", None,
                                                workers=["astra", "fable"],
                                                reviewers=["astra", "opus"]),
                         ("fable", "opus"))

    def test_a_named_reviewer_takes_another_labs_payg_executor_over_its_own_labs_sub(self):
        self.cfg["providers"]["beta"]["mode"] = "payg"
        self.cfg["models"]["fable"]["mode"] = "payg"
        self.providers = meters(acme=10, beta=10)
        self.assertEqual(staffing.pick_models(self.cfg, self.providers, None, "opus",
                                              self.logs.append, quiet=True,
                                              workers=["opus", "astra"],
                                              reviewers=["opus", "astra"]),
                         ("astra", "opus"))
        self.assertEqual(self.logs,
                         ["skipped opus: a marked reviewer of another lab can review astra"])
        self.logs.clear()
        self.assertEqual(staffing.pick_models(self.cfg, self.providers, None, "opus",
                                              self.logs.append, quiet=True,
                                              workers=["opus", "fable"], reviewers=["opus"]),
                         ("opus", "opus"))
        self.assertEqual(self.logs, [])
        self.providers = meters(acme=10, beta=100)
        self.assertEqual(staffing.pick_models(self.cfg, self.providers, None, "opus",
                                              self.logs.append, quiet=True,
                                              workers=["opus", "astra"],
                                              reviewers=["opus", "astra"]),
                         ("opus", "opus"))
        self.assertEqual(self.logs, [])
        with self.assertRaises(config.Error):
            staffing.pick_models(self.cfg, self.providers, None, "astra", None, quiet=True,
                                 workers=["opus", "astra"], reviewers=["opus"])
        self.providers = meters(acme=10, beta=10)
        self.providers.harnesses = {("test", "acme"): "acme is not logged in"}
        with self.assertRaises(config.Error):
            staffing.pick_models(self.cfg, self.providers, None, "opus", None, quiet=True,
                                 workers=["opus", "astra"], reviewers=["opus"])


class UnlistedModelLab(Sandbox):
    def setUp(self):
        super().setUp()
        self.cfg = {
            "defaults": {"orchestrator": "nova", "workers": ["nova", "dart", "bolt"]},
            "models": {
                "nova": {"harness": "claude", "model": "claude-nova-2", "effort": "high",
                         "provider": "anthropic"},
                "dart": {"harness": "opencode", "model": "dune/CLAUDE-dart-2", "effort": "high",
                         "provider": "dune"},
                "near": {"harness": "opencode", "model": "claudette-1", "effort": "high",
                         "provider": "dune"},
                "bolt": {"harness": "codex", "model": "bolt-3", "effort": "high",
                         "provider": "openai"},
            },
            "providers": {"anthropic": {}, "dune": {"maker": "Dune"}, "openai": {}},
        }

    def test_family_word_matches_spoken_and_resolves_unlisted_models(self):
        self.assertEqual(config.family("CLAUDE-nova-2", ["Claude"]), "Claude")
        self.assertEqual(config.family("claude", ["Claude"]), "Claude")
        self.assertIsNone(config.family("claudette-1", ["Claude"]))
        self.assertEqual(config.spoken("claude-nova-7-1", ["Claude"]), "Nova 7.1")
        self.assertEqual(config.spoken("gpt-5-5", ["GPT"]), "GPT 5.5")
        # With no lineup, the maker the family's manifest names is the lab, as `config.company`
        # names it: no provider's `maker` names `Anthropic`, so its name in lower case.  No family
        # word keeps the provider.
        self.assertEqual(staffing.lab(self.cfg, "nova", []), "anthropic")
        self.assertEqual(staffing.lab(self.cfg, "dart", []), "anthropic")
        self.assertEqual(staffing.lab(self.cfg, "near", []), "dune")
        self.assertEqual(staffing.lab(self.cfg, "bolt", []), "openai")
        self.assertEqual(staffing.pair_tier(self.cfg, "nova", "dart", []), 1)
        self.assertEqual(staffing.pair_tier(self.cfg, "nova", "bolt", []), 0)

    def test_a_familys_lab_is_the_maker_its_manifest_names(self):
        # A provider whose `maker` names the manifest's maker is that maker's lab.
        self.cfg["providers"]["acme"] = {"maker": "Anthropic"}
        self.assertEqual(staffing.lab(self.cfg, "nova", []), "acme")
        self.assertEqual(staffing.lab(self.cfg, "dart", []), "acme")
        del self.cfg["providers"]["acme"]
        # A second spelling of the word, declared first and naming no maker, reads the maker of
        # the manifest that declares the word and names one, across Unicode case variants too.
        spelled = [("acme", {"family": "CLAUDE"}),
                   ("claude", {"family": "Claude", "maker": "Anthropic"})]
        with patch.object(config, "manifests", return_value=spelled):
            self.assertEqual(config.family("claude-nova-2"), "CLAUDE")
            self.assertEqual(staffing.lab(self.cfg, "nova", []), "anthropic")
            self.assertEqual(staffing.lab(self.cfg, "dart", []), "anthropic")
        folded = [("acme", {"family": "Acme\u00df", "maker": "Dune"}),
                  ("other", {"family": "ACMESS"})]
        self.cfg["models"]["sharp"] = {"harness": "claude", "model": "acmess-nova",
                                       "effort": "high", "provider": "openai"}
        with patch.object(config, "manifests", return_value=folded):
            self.assertEqual(config.family("acmess-nova"), "ACMESS")
            self.assertEqual(staffing.lab(self.cfg, "sharp", []), "dune")
        # A manifest declaring the family and naming no maker leaves the word itself.
        with patch.object(config, "manifests", return_value=[("claude", {"family": "Claude"})]):
            self.assertEqual(staffing.lab(self.cfg, "nova", []), "Claude")
            self.assertEqual(staffing.lab(self.cfg, "dart", []), "Claude")
            self.assertEqual(staffing.lab(self.cfg, "near", []), "dune")

    def test_unlisted_model_takes_the_maker_of_a_row_holding_its_family(self):
        lineup = [{"release": "claude-nova-2", "name": "Nova 2", "board_name": "Claude Nova 2",
                   "maker": "Acme", "effort": "high", "values": {},
                   "yours": [{"harness": "claude", "model": "claude-nova-2"}]}]
        self.assertEqual(staffing.lab(self.cfg, "nova", lineup), "acme")
        self.assertEqual(staffing.lab(self.cfg, "dart", lineup), "acme")
        self.assertEqual(staffing.lab(self.cfg, "near", lineup), "dune")
        self.assertEqual(staffing.lab(self.cfg, "bolt", lineup), "openai")
        # A sibling row with a non-text maker names no maker: alone, the manifest's maker wins;
        # before a row naming a text maker, that later row wins.
        non_text = [{"release": "claude-other-1", "name": "Other 1", "board_name": "Other 1",
                     "maker": 17, "effort": "high", "values": {},
                     "yours": [{"harness": "opencode", "model": "dune/claude-other-1"}]}]
        self.assertEqual(staffing.lab(self.cfg, "nova", non_text), "anthropic")
        named = {"release": "claude-other-2", "name": "Other 2", "board_name": "Other 2",
                 "maker": "Dune", "effort": "high", "values": {},
                 "yours": [{"harness": "opencode", "model": "dune/claude-other-2"}]}
        self.assertEqual(staffing.lab(self.cfg, "nova", [*non_text, named]), "dune")
        # A row holding dart itself wins over any family word.
        held = [*lineup, {"release": "dart-2", "name": "Dart 2", "board_name": "Dart 2",
                          "maker": "Dune", "effort": "high", "values": {},
                          "yours": [{"harness": "opencode", "model": "dune/CLAUDE-dart-2"}]}]
        self.assertEqual(staffing.lab(self.cfg, "dart", held), "dune")

    def test_entries_without_a_model_id_fall_back_to_their_provider(self):
        self.cfg["models"]["num"] = {"harness": "claude", "model": 7, "effort": "high",
                                     "provider": "dune"}
        self.cfg["models"]["def_a"] = {"harness": "claude", "model": "default", "effort": "high",
                                       "provider": "anthropic"}
        self.cfg["models"]["def_b"] = {"harness": "codex", "model": "default", "effort": "high",
                                       "provider": "openai"}
        self.assertEqual(staffing.lab(self.cfg, "num", []), "dune")
        with patch.object(config, "families", return_value=["Default", "Claude"]):
            self.assertEqual(staffing.lab(self.cfg, "def_a", []), "anthropic")
            self.assertEqual(staffing.lab(self.cfg, "def_b", []), "openai")
            self.assertEqual(staffing.pair_tier(self.cfg, "def_a", "def_b", []), 0)

    def test_a_default_model_is_no_other_lab_than_a_sibling_on_its_harness_and_provider(self):
        self.cfg["providers"]["beta"] = {}
        self.cfg["models"].update({
            "nova_dune": {"harness": "claude", "model": "claude-nova-2", "effort": "high",
                          "provider": "dune"},
            "mist": {"harness": "claude", "model": "default", "effort": "high",
                     "provider": "dune"},
            "mist_beta": {"harness": "claude", "model": "default", "effort": "high",
                          "provider": "beta"},
            "mist_other_harness": {"harness": "opencode", "model": "default", "effort": "high",
                                   "provider": "dune"},
            "other": {"harness": "claude", "model": "claudette-1", "effort": "high",
                      "provider": "dune"},
        })
        self.assertEqual(staffing.lab(self.cfg, "nova_dune", []), "anthropic")
        self.assertEqual(staffing.lab(self.cfg, "mist", []), "dune")
        self.assertEqual(staffing.pair_tier(self.cfg, "nova_dune", "mist", []), 1)
        self.assertEqual(staffing.pair_tier(self.cfg, "mist", "nova_dune", []), 1)
        with patch.object(config, "manifests", return_value=[("claude", {"family": "Claude"})]):
            self.assertEqual(staffing.lab(self.cfg, "nova_dune", []), "Claude")
            self.assertEqual(staffing.pair_tier(self.cfg, "nova_dune", "mist", []), 1)
            self.assertEqual(staffing.pair_tier(self.cfg, "mist", "nova_dune", []), 1)
        self.assertEqual(staffing.pair_tier(self.cfg, "nova_dune", "mist_beta", []), 0)
        self.assertEqual(staffing.pair_tier(self.cfg, "nova", "mist", []), 0)
        self.assertEqual(staffing.pair_tier(self.cfg, "nova_dune", "mist_other_harness", []), 0)
        self.assertEqual(staffing.pair_tier(self.cfg, "nova_dune", "other", []), 0)
        held = [{"release": "mist-1", "name": "Mist 1", "board_name": "Mist 1",
                 "maker": "Dune", "effort": "high", "values": {},
                 "yours": [{"harness": "claude", "model": "default"}]}]
        self.assertEqual(staffing.pair_tier(self.cfg, "nova_dune", "mist", held), 0)

    def test_two_harnesses_defaults_on_one_provider_are_not_the_same_model(self):
        cfg = {"providers": {"dune": {}}, "models": {
            "nova": {"harness": "claude", "model": "default", "provider": "dune", "effort": "high"},
            "nova_low": {"harness": "claude", "model": "default", "provider": "dune", "effort": "low"},
            "mist": {"harness": "codex", "model": "default", "provider": "dune", "effort": "high"},
            "echo": {"harness": "claude", "model": "older-1", "provider": "dune", "effort": "high"},
            "echo_codex": {"harness": "codex", "model": "older-1", "provider": "dune", "effort": "high"},
        }}
        rows = [
            {"release": "current-1", "maker": "Acme",
             "yours": [{"harness": "claude", "model": "default"}]},
            {"release": "older-1", "maker": "Acme",
             "yours": [{"harness": "claude", "model": "older-1"},
                       {"harness": "codex", "model": "older-1"}]},
        ]
        self.assertTrue(staffing.same_model(cfg, "nova", "nova_low"))
        self.assertFalse(staffing.same_model(cfg, "nova", "mist"))
        self.assertTrue(staffing.same_model(cfg, "echo", "echo_codex"))
        self.assertEqual(staffing.pair_tier(cfg, "nova", "nova_low", rows), 2)
        self.assertEqual(staffing.pair_tier(cfg, "nova", "mist", rows), 0)
        self.assertEqual(staffing.pair_tier(cfg, "nova", "echo", rows), 1)
        self.assertEqual(staffing.pair_tier(cfg, "echo", "echo_codex", rows), 2)
        self.assertEqual(staffing.pair_tier(cfg, "nova", "mist", []), 1)
        with patch.object(staffing.matrix, "listed", return_value=(rows, {})):
            self.assertEqual(staffing.best_pair(cfg, ["nova"], ["mist", "echo"]), ("nova", "mist"))
            self.assertEqual(staffing.best_pair(cfg, ["echo"], ["echo_codex", "nova"]),
                             ("echo", "nova"))
            self.assertIsNone(staffing.best_pair(cfg, ["echo"], ["echo_codex"], allow_self=False))


if __name__ == "__main__":
    unittest.main()
