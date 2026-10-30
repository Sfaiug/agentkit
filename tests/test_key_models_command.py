"""`ak models` prints the models screen's answer per role, then ak's own run numbers per
configured model; `--json` gives each role's best and line of best quality for the money too.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_answer.py sets it up;
judged by the output and exit code.  Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import BUILDS, ENV, LEGEND, ORCH, REVIEWS, boards

OWN = ["model orch exec review", "mid   -    -    -", "bolt  -    -    -"]


class ModelsCommand(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n")
        akconfig.write(home, {"mid": {"harness": "claude", "model": "acme-mid-5", "effort": "low"},
                              "bolt": {"harness": "codex", "model": "bolt-3", "effort": "low"}})
        home.write(".agentkit/state/boards.json", boards())

    def models(self, *args):
        done = self.home.ak("models", *args, env={**ENV, "COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def test_each_role_s_answer_then_ak_s_own_numbers(self):
        shown = [line.rstrip() for line in self.models().splitlines()]
        at = shown.index(ORCH[0])
        answer = [*ORCH, *BUILDS, *REVIEWS, "", *LEGEND]
        self.assertEqual(shown[at:at + len(answer)], answer)
        self.assertEqual(shown[-3:], OWN)

    def test_json_gives_each_role_s_front_and_ak_s_own_numbers(self):
        found = json.loads(self.models("--json"))
        self.assertEqual(sorted(found), ["execute", "live", "orchestrate", "review"])
        self.assertEqual(round(found["execute"]["best"], 1), 100.0)
        self.assertEqual([(row["name"], row["effort"], round(row["quality"], 1), row["cost"],
                           row["notes"]) for row in found["execute"]["front"]], [
            ("Acme Max 5", "max", 100.0, 20.0, ["no harness"]),
            ("Acme Mid 5", "high", 97.8, 15.0, []),
            ("Acme Max 5", "high", 95.3, 10.0, ["pick", "no harness"]),
            ("Bolt 3", "medium", 93.2, 3.0, []),
            ("Crux 2", "low", 74.0, 1.0, ["1 missing"])])
        self.assertEqual(found["execute"]["front"][0]["release"], "acme-max-5")
        self.assertGreater(found["execute"]["front"][0]["se"], 0)
        self.assertEqual(found["live"], {name: dict.fromkeys(("orchestrate", "execute", "review"))
                                         for name in ("mid", "bolt")})


if __name__ == "__main__":
    unittest.main()
