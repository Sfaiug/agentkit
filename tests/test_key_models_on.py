"""ak compares and uses only the models on in your companies.  A listed model, a current release
with a score, is on when its maker is one of `companies` and its slug is not in `models_off`;
without `companies`, your companies are the makers of what `[defaults]` runs.  `ak models`
compares only the models on, and counts them among your companies' listed ones.  A configured
model running a listed release that is off is never picked, as `ak usage` shows its pick order
and review pair, nor does a seat start on it; with every model off `ak orch` refuses, naming
the model list, as `ak worker` and `ak orch --model` do one named outright, reaching no harness.
A model running a release without a score is not the list's to turn off.

Black-box: the program `AK_BIN` names runs from outside (tests/fixtures/akbin.py), its
harnesses fakes listing invented models and the boards held as just asked with the invented
rows of tests/test_key_models_answer.py, each release under the maker its name starts with
(Acme Max 5 and Acme Mid 5 under Acme, Bolt 3 under Bolt, Crux 2 under Crux), beside Crux
Flash 1, a release of Crux's with no score.  `ak models` stores the lineup every pick reads.
Judged by exit codes and what each command prints.  Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, aa, boards as scored

# each configured model: its harness, the release it runs and the effort it lists
MODELS = {"mid": {"harness": "claude", "model": "acme-mid-5", "effort": "high"},
          "bolt": {"harness": "codex", "model": "bolt-3", "effort": "high"},
          "crux": {"harness": "codex", "model": "crux-2", "effort": "low"},
          "flash": {"harness": "codex", "model": "crux-flash-1", "effort": "high"}}


def boards():
    held = scored()
    rows = held["artificialanalysis.ai"]["rows"]
    rows.append(aa("crux-flash-1", "Crux Flash 1", "high", {}))
    for row in rows:
        row["maker"] = row["model"].split()[0]
    return held


class ModelsOn(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n"
                                        "crux-flash-1\tCrux Flash 1\thigh\n")
        self.home.write(".agentkit/state/boards.json", boards())

    def ak(self, *args, code=0):
        done = self.home.ak(*args, env=ENV)
        self.assertEqual(done.code, code, done.out + done.err)
        return done

    def configure(self, models=MODELS, **given):
        """The config holding `models`, [defaults] and the top-level keys `given`, and the
        lineup `ak models` stores off it: what it compares and the line saying how many."""
        settings = {key: given.pop(key) for key in ("companies", "models_off") if key in given}
        akconfig.write(self.home, {name: MODELS[name] for name in models}, settings=settings,
                       **given)
        answer = json.loads(self.ak("models", "--json").out)
        line = next(line.strip() for line in self.ak("models").out.splitlines()
                    if "comparing" in line)
        return {row["release"] for role in ("orchestrate", "execute", "review")
                for row in answer[role]["front"]}, line.split(" · ")[0]

    def test_without_companies_the_defaults_makers_are_compared(self):
        # mid and bolt run Acme's and Bolt's releases; crux, in no [defaults], is not compared
        self.assertEqual(self.configure(orchestrator="mid", workers=["bolt"], reviewers=["mid"]),
                         ({"acme-max-5", "acme-mid-5", "bolt-3"}, "comparing all 3 models"))

    def test_companies_and_models_off_say_which_are_on(self):
        self.assertEqual(self.configure(companies=["Acme", "Crux"], models_off=["acme-max-5"]),
                         ({"acme-mid-5", "crux-2"}, "comparing 2 of 3 models"))

    def test_an_off_worker_or_reviewer_is_never_picked_and_an_unlisted_one_still_is(self):
        # crux is off as Crux is no company of yours, bolt as turned off; flash runs a release
        # without a score, which the list does not govern
        self.configure(workers=["mid", "bolt", "crux", "flash"],
                       reviewers=["bolt", "crux", "flash"], companies=["Acme", "Bolt"],
                       models_off=["bolt-3"])
        done = self.ak("usage", "--json")
        answer = json.loads(done.out)
        self.assertEqual(sorted(answer["pick_order"]), ["flash", "mid"])
        self.assertEqual(answer["review"]["reviewer"], "flash")
        self.assertIn(answer["review"]["executor"], ("mid", "flash"))
        text = self.ak("usage").err
        for name in ("bolt", "crux"):
            self.assertIn(f"pick executor: {name} excluded: off in the model list", text)

    def test_no_seat_starts_on_an_off_model_and_with_every_model_off_orch_refuses(self):
        self.configure(orchestrator="crux", companies=["Acme", "Bolt"])
        shown = self.ak("orch", "fix-api", "--dry-run").out.splitlines()
        launched = next(line.split()[1] for line in shown if line.startswith("orch: "))
        self.assertIn(launched, ("mid", "bolt", "flash"))
        self.configure(["mid", "bolt", "crux"], companies=[])
        done = self.ak("orch", "fix-api", "--dry-run", code=2)
        self.assertIn("model list", done.err)

    def test_an_off_model_named_outright_runs_no_turn_and_opens_no_seat(self):
        self.configure(companies=["Acme", "Bolt"])     # crux runs Crux's: no company of yours
        task = str(self.home.write("task.md", "Say hello.\n"))
        for role in ("executor", "reviewer"):
            done = self.ak("worker", "crux", task, "--workspace", str(self.home.path),
                           "--out", str(self.home.path / role), "--role", role, code=2)
            self.assertIn("model list", done.err)
        self.assertEqual(self.fakes["codex"].n, 0)
        done = self.ak("orch", "fix-api", "--model", "crux", "--dry-run", code=2)
        self.assertIn("model list", done.err)


if __name__ == "__main__":
    unittest.main()
