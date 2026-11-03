"""A turn placed where no machine with room outlives it by a rent and a pass (google_cloud.READY,
PASS) asks the tick for another machine, as a turn no machine takes does: it is ready by the time
the chosen one stops taking turns, which then come back to this host no more. One lasting long
enough, the chosen or another with room, asks for none.

Black-box, on tests/test_key_a_turn_packs_onto_the_busiest_machine.py's machines ak rents: the
need is the line the run leaves in `google-cloud-need` for the tick's next pass.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
import test_key_a_turn_packs_onto_the_busiest_machine as packs    # its tests run in their own file

# Seconds Google lets each live, from a minute ago: past a turn's hour (machine_turn.LENT_FOR)
# with minutes to start it, short of a rent and a pass more; and well past both.
SOON, LATER = 4200, 21600


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class AMachineEndingSoonIsReplacedInTime(unittest.TestCase):
    placed = packs.ATurnPacksOntoTheBusiestMachine.placed

    def needs(self, cpus, lives):
        """(turns and other containers per machine, whether the run noted a need)."""
        placed, asked = self.placed(cpus, lives)
        self.assertEqual(asked, [])    # placing asks Google nothing; the tick rents
        return placed, (self.home.path / ".agentkit/state/google-cloud-need").exists()

    def test_the_only_machine_with_room_ending_soon_notes_a_need(self):
        self.assertEqual(self.needs({"acme-soon": 8}, {"acme-soon": SOON}),
                         ({"acme-soon": (2, 1)}, True))

    def test_another_machine_with_room_lasting_longer_notes_none(self):
        self.assertEqual(self.needs({"acme-soon": 2, "acme-later": 8},
                                    {"acme-soon": SOON, "acme-later": LATER}),
                         ({"acme-soon": (2, 0), "acme-later": (0, 1)}, False))

    def test_a_machine_ending_past_the_look_ahead_notes_none(self):
        self.assertEqual(self.needs({"acme-later": 8}, {"acme-later": LATER}),
                         ({"acme-later": (2, 1)}, False))


if __name__ == "__main__":
    unittest.main()
