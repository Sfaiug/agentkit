"""A line typed into a harness's composer, drawn as the harness draws it."""
from pathlib import Path
import re
import sys
import textwrap

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agentkit import watch  # noqa: E402


def opencode_rows(base, text):
    """`text` in the box of OpenCode's prompt screen `base`: wrapped inside the box, never past
    its bottom edge, each row under the box's left edge."""
    inset = re.search(r"^( *)┃", base, re.M)[1]
    edge = re.search(r"^ *╹▀+", watch.strip_sgr(base), re.M)[0]
    return "\n".join(textwrap.fill(part, len(edge) - len(inset) - 3)
                     for part in text.split("\n")).replace("\n", "\n" + inset + "┃  ")
