"""A paid login whose provider has no model on and marked for a role says so after its price in
`ak usage`'s `a month` cell (`$8 · no role marks its models`) and is `marked` false in
`ak usage --json`.  A login whose provider has a model on and marked in `[defaults]` or a seat's
record reads as today and is `marked` true; one with no price says `-` either way, and on a narrow
terminal the `a month` cell folds at words as any cell does.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each of
the `claude`, `codex`, `antigravity` and `grokbuild` harnesses being tests/fixtures/meters.py's
script beside its shipped manifest, with invented logins and seat records written into its Home.
Fails against /bin/false.
"""

import json
from pathlib import Path
import shutil
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home

WIDE = {"COLUMNS": "200"}
NARROW = {"COLUMNS": "40"}
MODELS = {"anvil": "claude", "bolt": "codex", "crux": "antigravity", "dart": "grokbuild"}
# provider: (row label on `ak usage`, its login's plan)
PLANS = {"anthropic": ("Claude", "max 20x"),
         "openai": ("ChatGPT", "pro"),
         "google": ("Gemini", "Google AI Pro"),
         "xai": ("Grok", "X Premium")}


def card_month(out, label):
    """The `a month` value of `label`'s narrow card, joined across any folded lines."""
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{label} "))
    end = next((i for i in range(start + 1, len(lines)) if not lines[i]), len(lines))
    card = lines[start + 1:end]
    at = next(i for i, line in enumerate(card) if line.startswith("  a month "))
    parts = [card[at][len("  a month "):].strip()]
    for line in card[at + 1:]:
        if not line.startswith("    "):
            break
        parts.append(line.strip())
    return " ".join(parts)


class UsageSaysAPlanNoRoleMarks(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        meter = meters.install(self.home)
        for harness in ("claude", "codex", "antigravity", "grokbuild"):
            shutil.copy2(meter.dir / "echo.sh", meter.dir / f"{harness}.sh")
        for provider in PLANS:
            meter.week(provider, "default", used=50)
        self.plans = {provider: plan for provider, (_, plan) in PLANS.items()}

    def run_usage(self, *, orchestrator="anvil", workers=("anvil", "crux"), reviewers=None,
                  models_off=("crux",), seats=None, env=WIDE):
        settings = {"models_off": list(models_off)} if models_off else None
        akconfig.write(self.home, MODELS, orchestrator=orchestrator, workers=list(workers),
                       reviewers=list(reviewers) if reviewers is not None else None,
                       providers={name: {"mode": "subscription"} for name in PLANS},
                       settings=settings)
        self.home.write(".agentkit/state/logins.json", {
            provider: {"default": {"email": f"default@{provider}.test", "ends": None,
                                   "plan": plan, "checked_at": time.time()}}
            for provider, plan in self.plans.items()})
        for name, record in (seats or {}).items():
            self.home.write(f".agentkit/state/session-{name}.json", record)
        data = self.home.ak("usage", "--json")
        self.assertEqual(data.code, 0, data.out + data.err)
        text = self.home.ak("usage", env=env)
        self.assertEqual(text.code, 0, text.out + text.err)
        return json.loads(data.out)["providers"], text.out

    def test_four_priced_logins_say_which_have_no_marked_on_model(self):
        # anvil is marked by [defaults], bolt only by a seat record, crux is off in the model list
        # though in [defaults].workers, and dart is marked by nothing.
        found, text = self.run_usage(seats={"fix-api": {"orchestrator": "anvil",
                                                        "workers": ["bolt"]}})
        self.assertEqual({name: (found[name]["price"], found[name]["marked"],
                                 meters.cell(text, label, "a month"))
                          for name, (label, _) in PLANS.items()},
                         {"anthropic": (200, True, "$200"),
                          "openai": (200, True, "$200"),
                          "google": (19.99, False, "$19.99 · no role marks its models"),
                          "xai": (8, False, "$8 · no role marks its models")})

    def test_a_seat_or_defaults_reviewer_marks_its_provider(self):
        # bolt only as a seat's orchestrator, dart only as a seat's reviewer; crux off in the
        # model list stays unmarked even when named by a seat.
        found, text = self.run_usage(
            workers=("anvil",),
            seats={"fix-api": {"orchestrator": "bolt", "workers": ["crux"], "reviewers": ["dart"]}})
        self.assertEqual({name: (found[name]["marked"], meters.cell(text, label, "a month"))
                          for name, (label, _) in PLANS.items()},
                         {"anthropic": (True, "$200"),
                          "openai": (True, "$200"),
                          "google": (False, "$19.99 · no role marks its models"),
                          "xai": (True, "$8")})
        # With no seat record, [defaults].reviewers still marks its provider.
        (self.home.path / ".agentkit/state/session-fix-api.json").unlink()
        found, text = self.run_usage(workers=("anvil",), reviewers=("dart",), models_off=())
        self.assertEqual((found["xai"]["marked"], meters.cell(text, "Grok", "a month")),
                         (True, "$8"))
        self.assertEqual((found["openai"]["marked"], meters.cell(text, "ChatGPT", "a month")),
                         (False, "$200 · no role marks its models"))

    def test_an_unpriced_login_says_nothing_more_in_a_month(self):
        self.plans["xai"] = None
        found, text = self.run_usage(workers=("anvil",), models_off=())
        self.assertEqual((found["xai"]["price"], found["xai"]["marked"]), (None, False))
        self.assertEqual(meters.cell(text, "Grok", "a month"), "-")
        self.assertEqual(meters.cell(text, "Gemini", "a month"),
                         "$19.99 · no role marks its models")

    def test_narrow_cards_fold_the_a_month_cell_without_cutting_words(self):
        _, text = self.run_usage(seats={"fix-api": {"orchestrator": "anvil", "workers": ["bolt"]}},
                                 env=NARROW)
        for line in text.splitlines():
            self.assertLessEqual(len(line), 40, line)
            self.assertEqual(line, line.rstrip(), repr(line))
        self.assertEqual({name: card_month(text, label) for name, (label, _) in PLANS.items()},
                         {"anthropic": "$200",
                          "openai": "$200",
                          "google": "$19.99 · no role marks its models",
                          "xai": "$8 · no role marks its models"})

    def test_ascii_locale_prints_without_unicode_error(self):
        for env in ({"LC_ALL": "C", "PYTHONUTF8": "0"},
                    {"LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "ascii"}):
            for width in ("200", "40"):
                with self.subTest(env=env, width=width):
                    _, text = self.run_usage(
                        workers=("anvil",), models_off=(), env={"COLUMNS": width, **env})
                    self.assertTrue(text.isascii(), text)
                    if width == "200":
                        self.assertEqual(meters.cell(text, "Grok", "a month"),
                                         "USD 8, no role marks its models")
                    else:
                        self.assertEqual(card_month(text, "Grok"),
                                         "USD 8, no role marks its models")

    def test_medium_width_never_hides_another_providers_models_to_fit_the_note(self):
        akconfig.write(self.home, {"anvil-main": "claude", "anvil-alt": "claude",
                                   "dart": "grokbuild"},
                       orchestrator="anvil-main", workers=["anvil-main"],
                       providers={"anthropic": {"mode": "subscription"},
                                  "xai": {"mode": "subscription"}})
        self.home.write(".agentkit/state/logins.json", {"xai": {"default": {
            "email": "default@xai.test", "ends": None, "plan": "X Premium",
            "checked_at": time.time()}}})
        text = self.home.ak("usage", env={"COLUMNS": "120"})
        self.assertEqual(text.code, 0, text.out + text.err)
        self.assertIn("anvil-main", text.out)
        self.assertIn("anvil-alt", text.out)
        self.assertIn("$8 · no role marks its models", text.out)
        for line in text.out.splitlines():
            self.assertLessEqual(len(line), 120, line)


if __name__ == "__main__":
    unittest.main()
