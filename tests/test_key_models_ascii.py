"""Where stdout takes ASCII alone, `ak models` prints in ASCII: `, ` sets apart the parts of each
role's bar heading, of the line on the boards and of a usage cell, whose money takes its
currency's ISO code, and the first two clauses of the note under the tables.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_bars.py and
tests/test_key_models_own_tables.py set it up, in the C locale with Python's UTF-8 mode and
locale coercion off, and in a UTF-8 locale whose stdout PYTHONIOENCODING makes ASCII, so a
character outside ASCII stops it; judged by the output and exit code.  Fails against /bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from test_key_models_answer import ENV
from test_key_models_bars import ROWS, held
from test_key_models_own_tables import MODELS, used_home

ASCII = [{"LC_ALL": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"},
         {"LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "ascii"}]


class ModelsAscii(unittest.TestCase):
    def models(self, home, columns, env):
        """`ak models`'s lines on `columns` cells in `env`, every one ASCII."""
        done = home.ak("models", env={**ENV, **env, "COLUMNS": str(columns)})
        self.assertEqual(done.code, 0, done.err)
        self.assertTrue(done.out.isascii(), done.out)
        return done.out.splitlines()

    def test_a_comma_sets_apart_the_parts_of_the_bar_headings_and_the_boards_line(self):
        with Home() as home:
            held(home, ROWS)
            for env in ASCII:
                with self.subTest(env):
                    shown = self.models(home, 100, env)
                    for role in ("orchestrator", "executor", "reviewer"):
                        self.assertIn(f"  {role}, three choices, two more shaded", shown)
                    self.assertTrue([line for line in shown if line.startswith(
                        "  comparing all 6 models, boards read ")], shown)

    def test_usage_takes_its_currency_s_code_and_a_comma_before_its_share(self):
        home = used_home()
        self.addCleanup(home.close)
        akconfig.write(home, MODELS, orchestrator="nova", workers=["bolt"], reviewers=["crux"],
                       settings={"money": {"currency": "EUR"}},
                       providers={"anthropic": {"mode": "subscription", "accounts": ["default"]},
                                  "openai": {"mode": "subscription",
                                             "accounts": ["default", "second"]}})
        for env in ASCII:
            with self.subTest(env):
                shown = self.models(home, 120, env)
                self.assertTrue(next(line for line in shown if line.startswith(
                    "* Acme Nova 7 Plus")).endswith("  EUR 0.15, 0.4%"), shown)
                self.assertEqual(shown[-2:], [
                    "reviews and issues: per task, time and usage: per task that went live,",
                    "usage also as a share of one login's week on its plan"])


if __name__ == "__main__":
    unittest.main()
