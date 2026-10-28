"""`− remove` under a subscription's row takes that subscription alone while its provider has
another, its usual login too; only a provider's last subscription takes the provider and its
models along.

Before 28 Oct, `− remove` under a provider's usual login (`Claude I`) took the provider, its
models and every other subscription with it: an owner dropping a spent free `Gemini I` lost a
paid `Gemini II`.  A provider whose `accounts` no longer list `default` runs on the ones they
list, as one added since `+ add a subscription` gives each a fresh name does.

Black-box, on tests/test_key_removed_subscription_signs_out.py's terminal: Claude listing
`default`, `a1` and `b2`, ChatGPT its usual login alone.  Judged by the question asked,
config.toml and the logins left under a temporary HOME; this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from test_key_removed_subscription_signs_out import Subscriptions, row_at


class RemovingOneSubscriptionKeepsTheRest(Subscriptions):
    def test_the_usual_login_goes_alone(self):
        # the two left are numbered afresh, so it is `Claude III` that leaves the page
        screen = self.remove("Claude I", "  Remove Claude I?", gone="Claude III")
        self.assertIsNotNone(row_at(screen, "Claude I"))
        self.assertIsNotNone(row_at(screen, "Claude II"))
        saved = akconfig.read(self.home)
        self.assertEqual(saved["providers"]["anthropic"]["accounts"], ["a1", "b2"])
        self.assertEqual(set(saved["models"]), {"fable", "astra"})
        self.assertEqual(self.signed_in(),
                         {"": [False, False], "a1": [True, True], "b2": [True, True]})
        self.assertTrue(self.codex.exists())

    def test_the_last_subscription_takes_its_provider_and_its_models(self):
        self.remove("ChatGPT", "  Remove ChatGPT and its models?")
        saved = akconfig.read(self.home)
        self.assertEqual(list(saved["providers"]), ["anthropic"])
        self.assertEqual(saved["providers"]["anthropic"]["accounts"], ["default", "a1", "b2"])
        self.assertEqual(set(saved["models"]), {"fable"})
        self.assertEqual(len(self.fakes["codex"].calls("logout")), 1)
        self.assertEqual(self.signed_in(),
                         {"": [True, True], "a1": [True, True], "b2": [True, True]})


if __name__ == "__main__":
    unittest.main()
