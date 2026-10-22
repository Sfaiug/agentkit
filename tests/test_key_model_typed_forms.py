"""The commands ak's prompts teach a model to type are the commands ak answers to.

A model learns `ak hand-in finding`, `ak run status --history` or `ak plan add` from its
prompt, and checks one with `-h` before it types it: each form must answer with its own usage,
carrying the arguments and flags the prompt uses, or the model types what ak refuses.  A model
to run is named the same way, by its key in config.toml: that key runs its harness on its model
id and effort, and any other spelling of it -- `harness:model`, `key@effort`, the bare model
id -- is refused, naming it, before a turn starts.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, the turn on a scripted harness from
fakeadapter.py.
"""

from itertools import takewhile
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home

USAGE = {
    "orch project": "usage: ak orch project [SEAT] CHECKOUT",
    "wait": "usage: ak wait PR_URL|RUN_ID",
    "run stop": "usage: ak run stop ID [--keep]",
    "run resume": "usage: ak run resume ID [--rounds N] [--bg]",
    "plan": "usage: ak plan | ak plan add \"OUTCOME\" --check 'COMMAND' | ak plan check N "
            "'COMMAND'",
    "fetch": "usage: ak fetch PATH [PATH ...] | ak fetch --serve",
    "hand-in done": "usage: ak hand-in done",
    "hand-in blocked": 'usage: ak hand-in blocked "WHY"',
    "hand-in not-needed": 'usage: ak hand-in not-needed "WHY"',
    "hand-in finding": 'usage: ak hand-in finding PATH:LINE "WHAT" "WHY IT MATTERS" '
                       "(--run COMMAND | --quote LINES)",
    "hand-in dispute": 'usage: ak hand-in dispute PATH:LINE "WHY IT IS WRONG" '
                       "(--run COMMAND | --quote LINES)",
    "orch rules": "usage: ak orch rules CODE",
    "orch rename": "usage: ak orch rename [--auto] [OLD] NEW",
}
# Forms whose usage runs on: how it starts, and what a prompt has the model add to it.
CARRIES = {
    "run": ("usage: ak run ", "--bg", "--review-pr"),
    "run status": ("usage: ak run status ", "--history"),
    "notify needs": ('usage: ak notify needs "QUESTION"',),
    "hand-in follow-up": ("usage: ak hand-in follow-up PATH:LINE ", "--before"),
}


class TaughtCommands(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def helped(self, form):
        done = self.home.ak(*form.split(), "-h")
        self.assertEqual(done.code, 0, f"ak {form} -h: {done.err}")
        return done.out

    def test_each_taught_form_answers_with_its_own_usage_line(self):
        for form, usage in USAGE.items():
            with self.subTest(form):
                self.assertIn(usage, self.helped(form).splitlines())

    def test_the_usage_of_each_taught_form_carries_the_flags_the_prompt_adds(self):
        for form, (start, *flags) in CARRIES.items():
            with self.subTest(form):
                lines = self.helped(form).splitlines()
                first = next((n for n, line in enumerate(lines) if line.startswith(start)), None)
                self.assertIsNotNone(first, lines)
                usage = " ".join(takewhile(str.strip, lines[first:]))
                for flag in flags:
                    self.assertRegex(usage, rf"(?<![\w-]){re.escape(flag)}(?![\w-])")


class ModelNames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, {"beta": {"harness": "claude", "model": "acme-model-1",
                                           "effort": "low"}})
        cls.fake = fakeadapter.install(cls.home, claude="pass")["claude"]
        cls.task = cls.home.write("tasks/fix-api.md", "# Fix the API\n\n## Goal\nNothing.\n")
        cls.workspace = cls.home.path / "code" / "fix-api"
        cls.workspace.mkdir(parents=True)

    def worker(self, model):
        return self.home.ak("worker", model, str(self.task), "--workspace", str(self.workspace),
                            timeout=300)

    def test_its_config_key_runs_one_turn_on_its_harness_model_and_effort(self):
        turns = len(self.fake.runs())
        done = self.worker("beta")
        self.assertEqual(done.code, 0, done.out + done.err)
        runs = self.fake.runs()[turns:]
        self.assertEqual(len(runs), 1, runs)
        self.assertEqual(runs[0]["argv"][:3], ["acme-model-1", "low", str(self.workspace)])

    def test_any_other_spelling_of_it_is_refused_naming_it_and_runs_no_turn(self):
        for form in ("claude:acme-model-1", "claude:beta", "beta@low", "claude:beta@low",
                     "acme-model-1"):
            with self.subTest(form):
                turns = len(self.fake.runs())
                done = self.worker(form)
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertIn(form, done.err)
                # ... and the models config.toml does define, so the model can pick one
                self.assertIn("beta", done.err.replace(form, ""))
                self.assertEqual(len(self.fake.runs()), turns)


if __name__ == "__main__":
    unittest.main()
