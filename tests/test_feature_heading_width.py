"""Feature headings stay on one terminal row, including their highlight."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import menu, terminal


class FeatureHeadingWidth(unittest.TestCase):
    def test_count_gives_way_when_it_cannot_fit_beside_the_name(self):
        project = {"name": "acme", "switches": [{}] * 23}
        for width, expected in ((20, "acme"), (22, "acme"),
                                (23, "… 23 hidden features"),
                                (40, "acme 23 hidden features")):
            with self.subTest(width=width):
                self.assertEqual(terminal.plain(menu.v5o_header(project, width)), expected)

    def test_highlighted_headings_fit_and_keep_counts_whole_and_separate(self):
        for depth in (0, 24):
            with patch.object(terminal, "colour_depth", return_value=depth):
                for name in ("acme", "acme-long-project-name", "界面", "acme\u0301"):
                    for hidden in (0, 1, 23, 1234):
                        project = {"name": name, "switches": [{}] * hidden}
                        count = f"{hidden} hidden feature{'' if hidden == 1 else 's'}"
                        for width in (*range(2, 41), 100, 170):
                            with self.subTest(depth=depth, name=name, hidden=hidden, width=width):
                                heading = menu.v5o_header(project, width)
                                line = terminal.highlight("  " + heading)
                                self.assertLessEqual(terminal.cells(line), terminal.layout_width(width))
                                plain = terminal.plain(heading, spaced=True)
                                if "hidden" in plain:
                                    self.assertTrue(plain.endswith("  " + count), plain)
                                    self.assertTrue(plain[:-len(count)].strip(), plain)


if __name__ == "__main__":
    unittest.main()
