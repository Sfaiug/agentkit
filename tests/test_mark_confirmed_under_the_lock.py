"""A typed line's mark is confirmed only while tmux says, under the seat's send lock, that the
pane runs the process the pass pinned: a launch holding that lock may respawn the pane while the
pass waits for it, and a read tmux does not answer proves nothing (`watch._respawned`).
"""

from contextlib import contextmanager
import unittest
from unittest.mock import patch

from fixtures.seats import LINE, PANE, Seats
from agentkit import notify, orch, watch


class MarkUnderTheLock(Seats):
    def confirm(self, locked):
        """Whether LINE's mark from process 4242, its composer read empty, is delivered once the
        lock's holder leaves the pane's identity read answering `locked`."""
        answer = [(0, f"{PANE}\t4242")]

        def tmux(*args, **kw):
            if args[0] == "display-message" and args[-1] == "#{pane_id}\t#{pane_pid}":
                return answer[0]
            return self.tmux(*args, **kw)

        lock = notify.session_lock

        @contextmanager
        def launch(name):
            answer[0] = locked
            with lock(name) as held:
                yield held

        mark = {"line": LINE, "seat": self.seat["created"], "pid": 4242}
        with (patch.object(orch, "tmux_out", side_effect=tmux),
              patch.object(notify, "session_lock", side_effect=launch)):
            delivered = watch.type_at_prompt(self.seat, LINE, lambda _: None, cfg=self.cfg,
                                             typed=mark)
        self.assertEqual(self.typed, [])
        return delivered

    def test_the_process_it_went_into_confirms_it(self):
        self.assertTrue(self.confirm((0, f"{PANE}\t4242")))

    def test_a_process_started_since_does_not(self):
        self.assertFalse(self.confirm((0, f"{PANE}\t9000")))

    def test_a_read_tmux_does_not_answer_does_not(self):
        self.assertFalse(self.confirm((1, "timed out")))


if __name__ == "__main__":
    unittest.main()
