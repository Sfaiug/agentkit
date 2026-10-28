"""`ak orch list` reads the run records once, `--why` included.

A listing read every record once for its tallies, and then each seat read them all again for
its word and again for its bar (`watch.session_state`, `statusbar.redress`), twice more with
`--why`: over a minute on a host holding 21 seats and 4,852 records.  Now the listing's one pass
goes to every seat it looks at, as the menu's draw does, and each seat's word and `--why` block
are what they are when it reads the records itself.
Offline: run records in the sandbox HOME, seats' screens answered by a fake tmux.
"""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))     # its fixtures, when loaded by path
from fixtures.sandbox import Sandbox
from agentkit import config, orch, record, terminal, watch

PANE = (config.REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()


class OrchListReadsRunsOnce(Sandbox):
    def setUp(self):
        super().setUp()
        self.seats = [{"name": name, "path": str(self.root), "created": 9000 + n,
                       "attached": False} for n, name in enumerate(("fix-api", "acme", "beta"))]
        for seat in self.seats:
            config.save_session(self.cfg, seat["name"], "opus", ["astra"])
        for name, value in (("sessions", lambda: self.seats), ("inside", lambda: True),
                            ("slice_line", lambda: "no slice"),
                            ("tmux_out", lambda *a, **_k: (0, PANE if a[0] == "capture-pane"
                                                           else ""))):
            self.stack.enter_context(patch.object(orch, name, value))
        self.stack.enter_context(patch.object(terminal, "width", return_value=200))
        # fix-api has a run going, acme one stalled, beta only merged ones
        self.launched("going", "fix-api", state="running", started_at=9900)
        self.launched("stuck", "acme", state="stalled", started_at=9000)
        for n in range(40):
            self.launched(f"done-{n}", "beta", state="pass", merged=True, finished_at=9000 + n)

    def launched(self, name, seat, **fields):
        directory = config.RUNS / f"20261028-{len(list(config.RUNS.iterdir())):04d}-{name}"
        directory.mkdir()
        record.save_state(directory, {"run_id": directory.name, "title": name,
                                      "launched_session": seat, **fields})

    def listing(self, *argv):
        """What `ak orch list` prints, and how many passes over the run records it made."""
        passes = []
        run_dirs = record.run_dirs
        def counted():
            passes.append(1)
            return run_dirs()
        with patch.object(record, "run_dirs", counted), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.cmd_list(list(argv)), 0)
        return out.getvalue(), len(passes)

    def test_one_pass_and_the_words_and_blocks_each_seat_reads_for_itself(self):
        announce = watch.announce_state
        def reading_itself(session, **facts):
            facts.pop("records", None)
            return announce(session, **facts)
        for argv in ((), ("--why",)):
            with self.subTest(argv=argv):
                with patch.object(watch, "announce_state", reading_itself):
                    alone, _ = self.listing(*argv)
                said, passes = self.listing(*argv)
                self.assertEqual(passes, 1)
                self.assertEqual(said, alone)
                rows = [line for line in said.splitlines()
                        if line.startswith(("fix-api ", "acme ", "beta "))]
                self.assertEqual(len(rows), 3)
                for row, word in zip(rows, ("working", "needs you", "idle")):
                    self.assertIn(terminal.state_text(word), row)


if __name__ == "__main__":
    unittest.main()
