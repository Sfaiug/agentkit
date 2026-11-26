"""A line typed into an Antigravity seat is read in its composer over any number of background
commands: agy lists four of them under the composer and a row `↓ 1 more` for the rest, and with
that row drawn ak read nothing there, so the line got no Enter (26 Nov 2026).  The fixture is a
real agy 1.5.18 `capture-pane -p -e -J` capture from a 120×40 seat opened by
`adapters/antigravity.sh interactive` (2026-11-26, last 15 non-blank rows): five `sleep 300` left
running, four listed over `↓ 1 more`, no footer, a line typed and never sent.
"""
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import watch  # noqa: E402

PANE = (REPO / "tests/fixtures/antigravity-more-background-draft-pane.txt").read_text("utf-8")
ROWS = ["Run acme-fix ended PASS and merged; its result is in ~/fix-api/result.md, and the next "
        "task of the plan waits for", "your word before it starts."]


class ALineOverMoreBackgroundCommands(unittest.TestCase):
    def test_the_composer_reads_as_the_line_typed(self):
        rows = watch._composer_rows("antigravity", PANE, exact=True)
        self.assertEqual([row.strip() for row in rows], ROWS)
        self.assertEqual(watch.composer_draft("antigravity", PANE), "".join("".join(ROWS).split()))


if __name__ == "__main__":
    unittest.main()
