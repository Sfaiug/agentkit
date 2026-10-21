"""The weekly audit is a config setting: `[audit]` in config.toml says whether it runs and which
models orchestrate, execute and review it, `[defaults]`'s for whatever it leaves out, and the
`c` screen's `Weekly audit` row shows it and opens its page, a row a key.

Offline: a temporary HOME holding the shipped default config, and the screen read from a pipe
with its keys fed in, so no terminal, tmux or key is touched.
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
from agentkit.terminal import Key


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
                         "on · orch Opus 5.5 · builds Opus 5.5, GPT-6-Astra · reviews Opus 5.5, GPT-6-Astra")
        self.write('on = false\nworkers = []\nreviewers = ["astra"]\n')
        self.assertEqual(menu.audit_value(config.load()),
                         "off · orch Opus 5.5 · builds nobody · reviews GPT-6-Astra")

    def page(self, *keys):
        """The page against `keys`, then Esc until it is gone, on a phone's 40 columns; the
        lines of each frame it drew."""
        out = io.StringIO()
        with patch.object(terminal, "read_key", side_effect=[*map(Key, keys), *[Key("esc")] * 2]), \
                patch.object(terminal, "width", return_value=40), redirect_stdout(out):
            menu.config_audit(config.load())
        frames = [frame.splitlines() for frame in terminal.ANSI.sub("", out.getvalue()).split(
            "agentkit · config · weekly audit")[1:]]
        # a phone's 40 columns hold every line the page draws
        self.assertTrue(all(terminal.cells(line) <= 40 for frame in frames for line in frame))
        return frames

    def table(self):
        return tomllib.loads(self.path.read_text()).get("audit")

    def test_each_row_writes_its_key_at_once_keeping_the_rest(self):
        self.page("enter")                                   # On: off
        self.assertEqual(self.table(), {"on": False})
        # Orchestrator's list opens on the one it is, opus: fable is the one over it
        self.page("down", "enter", "up", "enter")
        self.assertEqual(self.table(), {"on": False, "orchestrator": "fable"})
        # Reviews' opens on the first reviewer; Enter takes it out, and the list stays open
        frames = self.page("down", "down", "down", "enter", "enter", "down", "down", "enter")
        self.assertEqual(self.table(), {"on": False, "orchestrator": "fable",
                                        "reviewers": ["astra", "spark"]})
        self.assertIn("    □ Opus 5.5", frames[-2])       # the last key's frame, before the Esc
        self.assertIn("›   ■ muse-spark-1.3-contributor", frames[-2])
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), "0o600")
        # both builders out: the orchestrator builds alone
        frames = self.page("down", "down", "enter", "enter", "down", "enter")
        self.assertEqual(self.table()["workers"], [])
        self.assertIn("› Builds        nobody", frames[-1])     # Esc: its row lit again
        self.assertEqual(config.audit(config.load()), {
            "on": False, "orchestrator": "fable", "workers": [], "reviewers": ["astra", "spark"]})

    def test_esc_closes_a_list_and_a_refused_change_writes_nothing(self):
        before = self.path.read_text()
        frames = self.page("down", "enter", "up")
        self.assertIn("    ● Opus 5.5", frames[-2])     # the list, opus marked and fable lit
        self.assertIn("›   ○ Fable 5.1", frames[-2])
        self.assertNotIn("○ Fable 5.1", "\n".join(frames[-1]))   # Esc closed it, on the page still
        self.assertEqual(self.path.read_text(), before)
        self.write('reviewers = ["astra"]\n')
        before = self.path.read_text()
        frames = self.page("down", "down", "down", "enter", "enter")   # the last reviewer out
        said = " ".join(" ".join(frames[-2]).split())
        self.assertIn("weekly audit: ~/.agentkit/config.toml: [audit].reviewers must name a model",
                      said)
        self.assertEqual(self.path.read_text(), before)

    def test_a_table_the_tick_cannot_read_is_mended_by_the_first_change(self):
        self.write('on = false\norchestrator = "nova"\n')
        frames = self.page()
        said = " ".join(" ".join(frames[-1]).split())
        self.assertIn("unknown model 'nova'", said)
        self.assertIn("On ○ off", said)                     # what reads is shown as it reads
        self.assertIn("Orchestrator Opus 5.5", said)
        self.page("down", "down", "enter", "down", "enter")   # astra out of the builders
        self.assertEqual(self.table(), {"on": False, "workers": ["opus"]})
        # an [audit] that is not a table has nothing to keep
        self.path.write_text('audit = "broken"\n' + (REPO / config.DEFAULT_CONFIG_NAME).read_text())
        self.assertIn("[audit] must be a table", menu.audit_value(config.load()))
        self.page("enter")
        self.assertEqual(self.table(), {"on": False})

    def test_c_shows_the_row_with_its_value_from_a_pipe(self):
        out = io.StringIO()
        with patch.object(menu, "read", side_effect=[]) as read, redirect_stdout(out):
            menu.show_config(False)
        self.assertEqual(read.call_count, 0)
        text = terminal.ANSI.sub("", out.getvalue())
        self.assertIn("Weekly audit", text)
        self.assertIn("on · orch Opus 5.5 · builds Opus 5.5, GPT-6-Astra · reviews Opus 5.5, GPT-6-Astra",
                      " ".join(text.split()))
        rows = [line.split()[0] for line in text.splitlines() if line.startswith("  ")]
        self.assertLess(rows.index("Discord"), rows.index("Weekly"))
        self.assertLess(rows.index("Weekly"), rows.index("Version"))


if __name__ == "__main__":
    unittest.main()
