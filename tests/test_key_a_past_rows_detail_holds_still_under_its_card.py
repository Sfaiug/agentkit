"""Under the past screen's Remove card, the pointer leaving its answers for the header leaves what
the row opened open, so Keep and Remove stay where they were (terminal.off_rows): black-box, on
tests/test_key_past_sessions_by_day.py's screen."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
from test_key_past_sessions_by_day import lines, opened


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class UnderItsCard(unittest.TestCase):
    def test_the_pointer_leaving_its_answers_moves_nothing_under_them(self):
        _home, menu, _screen = opened(self)
        menu.keys("x")
        card = menu.wait(lambda screen: "› ✓ Keep" in screen)
        menu.type("\x1b[<35;1;1M")         # onto `agentkit`: off the answers, Keep's mark goes
        moved = menu.wait(lambda screen: "✓ Keep" in screen and "› ✓ Keep" not in screen)
        rows = [[[n for n, line in enumerate(lines(shown)) if word in line]
                 for word in ("Ship the docs site.", "✓ Keep", "× Remove")]
                for shown in (card, moved)]
        self.assertEqual(rows[1], rows[0])
        self.assertEqual(rows[0][0], [4])


if __name__ == "__main__":
    unittest.main()
