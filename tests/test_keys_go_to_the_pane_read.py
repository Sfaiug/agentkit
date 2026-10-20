"""Every read and key of a line ak types goes to the pane its seat showed as the pass began, named
by id: a pane the owner selects after its composer was read empty, or moves into the seat, gets
none of ak's keys onto its draft, nor an Enter sending it.  Offline: fixtures.seats.
"""

import unittest
from unittest.mock import patch

from fixtures.seats import LINE, PANE, SEAT, Seats
from agentkit import orch, watch


class KeysGoToThePaneRead(Seats):
    def test_a_pane_selected_after_the_composer_read_gets_no_key(self):
        keys, selected, tmux = {PANE: [], "%9": []}, [PANE], self.tmux

        def server(*args, **kw):
            if args[0] == "send-keys":      # `=seat:` is whichever pane is selected as it is sent
                target = args[args.index("-t") + 1]
                keys[selected[0] if target == f"={SEAT}:" else target].append(args[-1])
            return tmux(*args, **kw)

        def selects(_session):              # the owner selects their notes before the first key
            selected[0] = "%9"
            return False

        with patch.object(orch, "tmux_out", side_effect=server), \
                patch.object(watch, "pane_unread", side_effect=selects):
            watch.type_at_prompt(self.seat, LINE, lambda _: None, cfg=self.cfg)
        self.assertEqual(keys, {PANE: [LINE, "Enter"], "%9": []})


if __name__ == "__main__":
    unittest.main()
