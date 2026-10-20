"""The vision changes only with the owner's yes: AGENTS.md's `What ak is for` is this text, word for
word, so a change to it is a visible change to this test (the owner's text of 15 Oct 2026, its
last line's word maximum of 16 Oct).

Offline: the checkout's own AGENTS.md.
"""

from pathlib import Path
import textwrap
import unittest

REPO = Path(__file__).resolve().parents[1]

VISION = textwrap.dedent("""\
    ## What ak is for

    ak builds whatever you want, with AI models doing the work. You state an intent and get the finished result, live, for any project, on any machine, with any model. It always takes one path: intent → alignment → build → review → live, and what breaks live comes back in as a new intent. Alignment is the only part done with you: from 0 to 1 together, until the goal is clear and checkable; from 1 to 100 alone, asking only what only you can answer. One model builds, another reviews, round after round until the work passes, and nothing ever gets stuck: whatever fails recovers by itself.

    Every change to ak is judged by what it does for what you build with it, and by these four rules:

    1. **Less.** Use the fewest features, steps, options and concepts that reach the goal. The best part is no part, and the best process is no process. ak decides everything it can and never offers a choice it could make itself. It explains itself in plain words, so nobody needs a manual. If an addition is not a clear yes, it is a no.
    2. **Quality, then speed, then cost.** Quality is the result doing what you asked and staying that way. The ideal is the best result, instantly, for nothing. When two of these pull apart, the one earlier in this list wins.
    3. **Models are fuel; ak is the car.** ak stays the same while models and the programs that run them come and go. It runs whichever is best at the time and depends on none. Swapping one changes quality, speed and cost, never whether the intent gets delivered.
    4. **ak enforces; words only explain.** Nothing depends on a model remembering an instruction or judging well on its own. A rule that can be a check, gate or hook is one, and it holds whatever model runs. A rule that lives only in text is unfinished.

    This section changes only with the owner's yes. Every other line has one home, and ak's instruction files a word maximum that only goes down; ak's orchestrators improve the rest on their own.""")


class Vision(unittest.TestCase):
    def test_the_vision_is_the_owners_text(self):
        # the whole section: the next one starts right after its last line
        self.assertIn(f"\n{VISION}\n\n## ", (REPO / "AGENTS.md").read_text())


if __name__ == "__main__":
    unittest.main()
