"""Go's `ak worker` opens each role's prompt with the words and rules Python's does.

go/internal/worker/rules holds a copy of agentkit/worker.py's PREAMBLES, one <role>.md each, and
of the review's GATE and the REAL_USERS rule that follows it where a project's users are real,
gate.md and real-users.md, each with a newline after it, so a change to either program's copy
that leaves the other behind fails here; `go generate ./internal/worker` in go/ copies them again.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import worker  # noqa: E402

COPY = REPO / "go/internal/worker/rules"


class Rules(unittest.TestCase):
    def test_go_holds_python_s_openings_and_rules(self):
        python = {**worker.PREAMBLES, "gate": worker.GATE, "real-users": worker.REAL_USERS}
        self.assertEqual({path.name: path.read_text() for path in COPY.iterdir()},
                         {f"{name}.md": f"{text}\n" for name, text in python.items()},
                         "run `go generate ./internal/worker` in go/")


if __name__ == "__main__":
    unittest.main()
