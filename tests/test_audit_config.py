"""The weekly audit is a config setting: `[audit]` in config.toml says whether it runs, off until
it says on, and which models orchestrate, execute and review it, `[defaults]`'s for whatever it
leaves out; its page shows it and writes it, a row a key.  `c` lists no row for it since 10 Nov
2026 (menu.CONFIG_ROWS), so the page is called here.

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

    def test_the_setting_is_off_with_the_defaults_until_the_table_says_otherwise(self):
        cfg = config.load()
        self.assertEqual(config.audit(cfg), {
            "on": False, "orchestrator": "opus", "workers": ["opus", "astra"],
            "reviewers": ["opus", "astra"]})
        self.write('on = true\norchestrator = "fable"\nworkers = []\nreviewers = ["astra"]\n')
        self.assertEqual(config.audit(config.load()), {
            "on": True, "orchestrator": "fable", "workers": [], "reviewers": ["astra"]})
        self.write('reviewers = ["astra"]\n')       # the rest stays the defaults'
        self.assertEqual(config.audit(config.load()), {
            "on": False, "orchestrator": "opus", "workers": ["opus", "astra"], "reviewers": ["astra"]})

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
        # the row's value shows that same line instead of a value
        self.write('orchestrator = "nova"\n')
        self.assertIn("unknown model 'nova'", menu.audit_value(config.load()))

    def test_the_row_says_on_or_off_and_the_three_roles_by_full_name(self):
        self.assertEqual(menu.audit_value(config.load()),
                         "off · orch Opus 5.5 · builds Opus 5.5, 6 Astra · reviews Opus 5.5, 6 Astra")
        self.write('on = true\nworkers = []\nreviewers = ["astra"]\n')
        self.assertEqual(menu.audit_value(config.load()),
                         "on · orch Opus 5.5 · builds nobody · reviews 6 Astra")

    def page(self, *keys):
        """The page against `keys`, then Esc until it is gone, on a phone's 40 columns; the
        lines of each frame it drew."""
        out = io.StringIO()
        with patch.object(terminal, "read_key", side_effect=[
                *(key if isinstance(key, Key) else Key(key) for key in keys), *[Key("esc")] * 2]), \
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
        self.page("space")                                   # On: on
        self.assertEqual(self.table(), {"on": True})
        # Orchestrator's list opens on the one it is, opus: fable is the one over it
        self.page("down", "enter", "up", "enter")
        self.assertEqual(self.table(), {"on": True, "orchestrator": "fable"})
        # Reviews' opens on the first reviewer; Space takes it out, and the list stays open
        frames = self.page("down", "down", "down", "enter", "space", "down", "down", "space")
        self.assertEqual(self.table(), {"on": True, "orchestrator": "fable",
                                        "reviewers": ["astra", "spark"]})
        self.assertIn("    □ Opus 5.5", frames[-2])       # the last key's frame, before the Esc
        self.assertIn("›   ■ Spark 1.3 Contributor", frames[-2])
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), "0o600")
        # both builders out: the orchestrator builds alone
        frames = self.page("down", "down", "enter", "space", "down", "space")
        self.assertEqual(self.table()["workers"], [])
        self.assertIn("› Builds        nobody", frames[-1])     # Esc: its row lit again
        self.assertEqual(config.audit(config.load()), {
            "on": True, "orchestrator": "fable", "workers": [], "reviewers": ["astra", "spark"]})

    def test_esc_closes_a_list_and_a_refused_change_writes_nothing(self):
        before = self.path.read_text()
        frames = self.page("down", "enter", "up")
        self.assertIn("    ● Opus 5.5", frames[-2])     # the list, opus marked and fable lit
        self.assertIn("›   ○ Fable 5.1", frames[-2])
        self.assertNotIn("○ Fable 5.1", "\n".join(frames[-1]))   # Esc closed it, on the page still
        self.assertEqual(self.path.read_text(), before)
        # a click past On's line is on nothing: the list stays open, nothing written
        frames = self.page("down", "enter", Key("click", col=30, row=3), "down")
        self.assertIn("›   ● Opus 5.5", frames[-3])
        self.assertIn("›   ○ 6 Astra", frames[-2])
        self.assertEqual(self.path.read_text(), before)
        self.write('reviewers = ["astra"]\n')
        before = self.path.read_text()
        frames = self.page("down", "down", "down", "enter", "space")   # the last reviewer out
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
        self.page("down", "down", "enter", "down", "space")   # astra out of the builders
        self.assertEqual(self.table(), {"on": False, "workers": ["opus"]})
        # an [audit] that is not a table has nothing to keep
        self.path.write_text('audit = "broken"\n' + (REPO / config.DEFAULT_CONFIG_NAME).read_text())
        self.assertIn("[audit] must be a table", menu.audit_value(config.load()))
        self.page("space")
        self.assertEqual(self.table(), {"on": True})

    def test_a_long_name_is_never_cut_on_the_page(self):
        self.write('orchestrator = "spark"\nworkers = ["spark"]\nreviewers = ["spark"]\n')
        page = "\n".join(self.page()[-1])
        self.assertNotIn("…", page)
        for role in ("Orchestrator", "Builds", "Reviews"):
            self.assertIn(f"  {role}", page)


if __name__ == "__main__":
    unittest.main()
