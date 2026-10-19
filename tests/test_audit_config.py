"""The weekly audit is a config setting: `[audit]` in config.toml says whether it runs and which
models orchestrate, execute and review it, `[defaults]`'s for whatever it leaves out, and the
`c` screen's `Weekly audit` row shows and edits it.

Offline: a temporary HOME holding the shipped default config, the screen read from a pipe, and
the row's questions answered through the menu's `read` seam, so no terminal, tmux or key is
touched.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, terminal

ESC = "\x1b"


class AuditSetting(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-audit-config-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / ".agentkit"
        self.home.mkdir()
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            patcher = patch.object(config, name,
                                   self.home if name == "HOME" else self.home / name.lower())
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {"HOME": str(tmp.name), "NO_COLOR": "1",
                                      "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
        env.start()
        self.addCleanup(env.stop)
        self.path = self.home / config.CONFIG_NAME
        self.path.write_text((REPO / config.DEFAULT_CONFIG_NAME).read_text())

    def write(self, table):
        self.path.write_text((REPO / config.DEFAULT_CONFIG_NAME).read_text() + "\n[audit]\n"
                             + table)

    def test_the_setting_is_on_with_the_defaults_until_the_table_says_otherwise(self):
        cfg = config.load()
        self.assertEqual(config.audit(cfg), {
            "on": True, "orchestrator": "opus", "workers": ["opus", "astra"],
            "reviewers": ["opus", "astra"]})
        self.write('on = false\norchestrator = "fable"\nworkers = []\nreviewers = ["astra"]\n')
        self.assertEqual(config.audit(config.load()), {
            "on": False, "orchestrator": "fable", "workers": [], "reviewers": ["astra"]})
        self.write('reviewers = ["astra"]\n')       # the rest stays the defaults'
        self.assertEqual(config.audit(config.load()), {
            "on": True, "orchestrator": "opus", "workers": ["opus", "astra"], "reviewers": ["astra"]})

    def test_a_setting_the_config_cannot_read_is_an_error_that_names_it(self):
        for table, words in (('orchestrator = "nova"\n', "unknown model 'nova'"),
                             ('workers = ["opus", "nova"]\n', "unknown model 'nova'"),
                             ('reviewers = []\n', "[audit].reviewers must name a model"),
                             ('on = "yes"\n', "[audit].on must be true or false"),
                             ('workers = "opus"\n', "[audit].workers must list model names")):
            self.write(table)
            with self.assertRaises(config.Error) as caught:
                config.audit(config.load())
            self.assertIn(words, str(caught.exception))
        # the row shows that same line instead of a value
        self.write('orchestrator = "nova"\n')
        self.assertIn("unknown model 'nova'", menu.audit_value(config.load()))

    def test_the_row_says_on_or_off_and_the_three_roles(self):
        self.assertEqual(menu.audit_value(config.load()),
                         "on · orch opus · builds opus, astra · reviews opus, astra")
        self.write('on = false\nworkers = []\nreviewers = ["astra"]\n')
        self.assertEqual(menu.audit_value(config.load()),
                         "off · orch opus · builds nobody · reviews astra")

    def step(self, *answers):
        with patch.object(menu, "read", side_effect=list(answers)) as read, \
                patch.object(menu, "pause") as pause, patch.object(terminal, "width", return_value=40), \
                patch.object(terminal, "frame") as frame, redirect_stdout(io.StringIO()):
            menu.config_audit(config.load())
        # a phone's 40 columns hold every line the screen draws and every question with room to type
        self.assertTrue(all(terminal.cells(line) <= 40 for line in frame.call_args.args[1]))
        self.assertTrue(all(terminal.cells(call.args[0]) <= 20 for call in read.call_args_list))
        return read, pause

    def table(self):
        return tomllib.loads(self.path.read_text()).get("audit")

    def test_enter_asks_four_questions_and_writes_the_table_keeping_what_was_not_answered(self):
        read, pause = self.step("off", "fable", "", "astra")
        self.assertEqual([call.args[0] for call in read.call_args_list],
                         ["On (on/off): ", "Orchestrator: ", "Executors: ", "Reviewers: "])
        self.assertEqual(pause.call_count, 0)
        self.assertEqual(self.table(), {"on": False, "orchestrator": "fable", "reviewers": ["astra"]})
        self.assertEqual(config.audit(config.load()), {
            "on": False, "orchestrator": "fable", "workers": ["opus", "astra"], "reviewers": ["astra"]})
        # the next edit keeps the table's other values; `none` empties the executors
        read, pause = self.step("", "", "none", "")
        self.assertEqual(self.table(), {"on": False, "orchestrator": "fable", "workers": [],
                                        "reviewers": ["astra"]})
        before = self.path.read_text()
        read, pause = self.step("on", "", "opus astra", "opus")
        self.assertEqual(self.table(), {"on": True, "orchestrator": "fable",
                                        "workers": ["opus", "astra"], "reviewers": ["opus"]})
        self.assertNotEqual(self.path.read_text(), before)
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), "0o600")
        # an [audit] that is not a table is shown as its error, and the answers replace it
        self.path.write_text('audit = "broken"\n' + (REPO / config.DEFAULT_CONFIG_NAME).read_text())
        self.assertIn("[audit] must be a table", menu.audit_value(config.load()))
        read, pause = self.step("off", "", "", "")
        self.assertEqual(pause.call_count, 0)
        self.assertEqual(self.table(), {"on": False})

    def test_esc_and_a_refused_answer_write_nothing(self):
        before = self.path.read_text()
        for answers in ((ESC,), ("on", ESC), ("on", "opus", ESC), ("on", "opus", "", ESC)):
            read, pause = self.step(*answers)
            self.assertEqual(read.call_count, len(answers))
            self.assertEqual(pause.call_count, 0)
            self.assertEqual(self.path.read_text(), before)
        for answers, words in ((("yes", "", "", ""), "on or off, not 'yes'"),
                               (("", "nova", "", ""), "unknown model 'nova'"),
                               (("", "", "opus none", ""), "unknown model 'none'"),
                               (("", "", "", "none"), "unknown model 'none'")):
            read, pause = self.step(*answers)
            self.assertEqual(pause.call_count, 1)
            self.assertIn(words, pause.call_args.args[0])
            self.assertEqual(self.path.read_text(), before)

    def test_none_empties_the_executors_only_as_the_whole_answer(self):
        # a model named none is a name like any other: it reviews, and executes beside another
        cfg = config.load()
        cfg["models"]["none"] = dict(cfg["models"]["astra"])
        config.save(cfg)
        self.step("", "", "opus none", "none")
        self.assertEqual(self.table(), {"workers": ["opus", "none"], "reviewers": ["none"]})
        self.assertEqual(config.audit(config.load())["reviewers"], ["none"])
        self.step("", "", "none", "")
        self.assertEqual(self.table(), {"workers": [], "reviewers": ["none"]})

    def test_c_shows_the_row_with_its_value_from_a_pipe(self):
        out = io.StringIO()
        with patch.object(menu, "read", side_effect=[]) as read, redirect_stdout(out):
            menu.show_config(False)
        self.assertEqual(read.call_count, 0)
        text = terminal.ANSI.sub("", out.getvalue())
        self.assertIn("Weekly audit", text)
        self.assertIn("on · orch opus · builds opus, astra · reviews opus, astra", text)
        rows = [line.split()[0] for line in text.splitlines() if line.startswith("  ")]
        self.assertLess(rows.index("Discord"), rows.index("Weekly"))
        self.assertLess(rows.index("Weekly"), rows.index("Version"))


if __name__ == "__main__":
    unittest.main()
