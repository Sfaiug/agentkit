"""A seat nobody named is called after a Star Wars: The Clone Wars character until its
orchestrator names it for its job: one word, one no seat or rename has, picked at random
(`orch.character_name`), so the menu reads `ahsoka` and `rex` rather than `new-35`.  Once every
one is taken, one of them is made unique as a typed name is (`orch.unique_name`).
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import orch


class CharacterNames(unittest.TestCase):
    def test_each_is_one_word_a_seat_can_be_called(self):
        self.assertEqual(len(set(orch.CHARACTERS)), len(orch.CHARACTERS))
        for name in orch.CHARACTERS:
            self.assertRegex(name, r"^[a-z]+$")
            self.assertEqual(orch.session_name(name), name)

    def test_a_free_one_is_picked_at_random(self):
        free = orch.CHARACTERS[:3]
        offered = []
        name = orch.character_name(set(orch.CHARACTERS[3:]),
                                   pick=lambda names: offered.extend(names) or names[-1])
        self.assertEqual(offered, list(free))      # every free one, and none taken
        self.assertEqual(name, free[-1])
        self.assertIn(orch.character_name(set()), orch.CHARACTERS)

    def test_once_every_one_is_taken_one_is_made_unique(self):
        taken = set(orch.CHARACTERS) | {"rex-2"}
        self.assertEqual(orch.character_name(taken, pick=lambda names: "rex"), "rex-3")

    def test_rebels_only_wullffwarro_is_not_used(self):
        taken = set(orch.CHARACTERS) - {"wullffwarro"}
        self.assertNotEqual(orch.character_name(taken), "wullffwarro")


if __name__ == "__main__":
    unittest.main()
