"""A seat's scope whose `cpu.pressure` a tick leaves unread has waited no less for it: read again,
all it ever waited is no part of the interval, and a seat idle since hears nothing.  Where none is
ever read, a kernel that counts no waiting, what a scope uses alone counts."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import cores

WAITED = "some avg10=0.00 avg60=0.00 avg300=0.00 total=170000000\n"


class AScopeWhoseWaitingIsUnreadIsUnread(unittest.TestCase):
    def told(self, ticks):
        """Whether acme is owed a line after `ticks`, (CPU seconds used by then, waiting read)."""
        owed, state = Mock(), {}
        with TemporaryDirectory() as slice_:
            scope = Path(slice_, "agentkit-seat-acme-89abcdef.scope")
            scope.mkdir()
            with patch.object(cores, "_now", side_effect=range(0, 180 * len(ticks), 180)), \
                    patch.multiple(cores.front, scopes=lambda: {scope: "acme"}, seat_now=str), \
                    patch.multiple(cores.watch, seat_read=lambda name: {}, owe_line=owed), \
                    patch.object(cores.host, "cpu_ticks", return_value={}):
                for used, read in ticks:
                    (scope / "cpu.stat").write_text(f"usage_usec {used * 1_000_000}\n")
                    (scope / "cpu.pressure").unlink(missing_ok=True)
                    if read:
                        (scope / "cpu.pressure").write_text(WAITED)
                    cores.tell(state, lambda line: None)
        return owed.called

    def test_an_idle_seat_whose_waiting_was_unread_for_a_tick_hears_nothing(self):
        self.assertFalse(self.told([(200, True), (560, False), (560, True)]))

    def test_on_a_kernel_that_counts_no_waiting_a_seat_holding_a_core_is_told(self):
        self.assertTrue(self.told([(0, False), (180, False), (360, False)]))


if __name__ == "__main__":
    unittest.main()
