"""ak compares and uses only the models on in your companies.  A listed model, a current release
with a score, is on when its maker is one of `companies` and its slug is not in `models_off`;
without `companies`, your companies are the makers of what `[defaults]` runs.  `ak models
--json` compares only the models on.  A configured model running a listed release that is off
is never picked, as `ak usage` shows its pick order and review pair, nor does a seat start on
it; with every model off `ak orch` refuses, naming the model list, as `ak worker` and `ak orch
--model` do one named outright, reaching no harness.  A model running a release without a score
is not the list's to turn off, but for one `models_off` holds: that stays off once the board
takes its scores, or its row, as one on stays on.

Black-box: the program `AK_BIN` names runs from outside (tests/fixtures/akbin.py), its
harnesses fakes listing invented models and the boards held as just asked with the invented
rows of tests/test_key_models_answer.py, each release under the maker its name starts with
(Acme Max 5 and Acme Mid 5 under Acme, Bolt 3 under Bolt, Crux 2 under Crux), beside Crux
Flash 1, a release of Crux's with no score.  `ak models --json` stores the lineup every pick
reads.  Judged by exit codes and what each command prints.  Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, NOW, aa, boards as scored

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


# Bolt 3's rows day after day as the boards retire it: kept, without scores, gone
RETIRING = (lambda row: row, lambda row: {**row, "values": {}}, lambda row: None)


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
        lineup `ak models --json` stores off it: what it compares."""
        settings = {key: given.pop(key) for key in ("companies", "models_off") if key in given}
        akconfig.write(self.home, {name: MODELS[name] for name in models}, settings=settings,
                       **given)
        answer = json.loads(self.ak("models", "--json").out)
        return {row["release"] for role in ("orchestrate", "execute", "review")
                for row in answer[role]["front"]}

    def test_without_companies_the_defaults_makers_are_compared(self):
        # mid and bolt run Acme's and Bolt's releases; crux, in no [defaults], is not compared
        self.assertEqual(self.configure(orchestrator="mid", workers=["bolt"], reviewers=["mid"]),
                         {"acme-max-5", "acme-mid-5", "bolt-3"})

    def test_companies_and_models_off_say_which_are_on(self):
        self.assertEqual(self.configure(companies=["Acme", "Crux"], models_off=["acme-max-5"]),
                         {"acme-mid-5", "crux-2"})

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

    def retire_bolt(self):
        """Store the boards each day of `RETIRING`, read anew: `ak models` stores them."""
        held = boards()
        for day, kept in enumerate(RETIRING, 1):
            for board in held.values():
                board["rows"] = [one for row in board["rows"]
                                 for one in [kept(row) if row["model"] == "Bolt 3" else row] if one]
                board["fetched_at"] = NOW + day * 86400
            self.home.write(".agentkit/state/boards.json", held)
            yield

    def test_a_model_on_stays_on_when_the_boards_list_it_no_more(self):
        # bolt runs Bolt 3, a release of yours on: picked as the boards take its scores, its rows
        for _ in self.retire_bolt():
            self.configure(workers=["mid", "bolt"], companies=["Acme", "Bolt"])
            answer = json.loads(self.ak("usage", "--json").out)
            self.assertEqual(sorted(answer["pick_order"]), ["bolt", "mid"])

    def test_a_model_turned_off_stays_off_when_the_boards_list_it_no_more(self):
        # bolt runs Bolt 3, which you turned off: the boards take its scores, then its rows
        for _ in self.retire_bolt():
            self.configure(orchestrator="bolt", workers=["mid", "bolt"],
                           reviewers=["bolt", "mid"], companies=["Acme", "Bolt"],
                           models_off=["bolt-3"])
            answer = json.loads(self.ak("usage", "--json").out)
            self.assertEqual(answer["pick_order"], ["mid"])
            self.assertEqual((answer["review"]["executor"], answer["review"]["reviewer"]),
                             ("mid", "mid"))
            shown = self.ak("orch", "fix-api", "--dry-run").out.splitlines()
            self.assertEqual(next(line.split()[1] for line in shown if line.startswith("orch: ")),
                             "mid")
            task = str(self.home.write("task.md", "Say hello.\n"))
            done = self.ak("worker", "bolt", task, "--workspace", str(self.home.path),
                           "--out", str(self.home.path / "out"), code=2)
            self.assertIn("model list", done.err)
            done = self.ak("orch", "fix-api", "--model", "bolt", "--dry-run", code=2)
            self.assertIn("model list", done.err)
        self.assertEqual(self.fakes["codex"].n, 0)

    def test_a_model_off_by_its_company_alone_is_picked_once_its_release_is_unrated(self):
        # bolt runs Bolt 3, off as Bolt is no company of yours, in no `models_off`: its scores
        # gone, the list governs it no more, which its owner left so (matrix.off)
        picked = []
        for _ in self.retire_bolt():
            self.configure(workers=["mid", "bolt"], companies=["Acme"])
            picked.append(sorted(json.loads(self.ak("usage", "--json").out)["pick_order"]))
        self.assertEqual(picked, [["mid"], ["bolt", "mid"], ["bolt", "mid"]])


if __name__ == "__main__":
    unittest.main()
