"""Only a seat working on ak reads `What ak is for`: once, inside ak's own AGENTS.md, which its
rulebook carries as that project's; an unfiled seat, or one filed under any other project,
reads none of it.

Offline: throwaway clones in a temporary HOME.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config  # noqa: E402

HEADING = "## What ak is for"


class VisionOnlyForAkSeats(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        home = self.root / "home"
        (home / ".agentkit/state").mkdir(parents=True)
        stack.enter_context(patch.object(config, "HOME", home / ".agentkit"))
        stack.enter_context(patch.object(config, "STATE", home / ".agentkit/state"))
        stack.enter_context(patch.dict(os.environ, {"HOME": str(home)}))

    def clone(self, name, agents):
        """A checkout of `name` whose origin's default branch holds `agents` as AGENTS.md."""
        upstream, checkout = self.root / f"{name}-origin", self.root / name
        git = lambda cwd, *args: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                                                 *args], cwd=cwd, check=True, capture_output=True)
        git(self.root, "init", "-q", "-b", "main", str(upstream))
        (upstream / "AGENTS.md").write_text(agents)
        git(upstream, "add", "AGENTS.md")
        git(upstream, "commit", "-qm", "rules")
        git(self.root, "clone", "-q", str(upstream), str(checkout))
        return str(checkout)

    def rulebook(self, record):
        with patch.object(config, "session_records", return_value={"acme": record}):
            return config.seat_rulebook("acme")

    def test_only_a_seat_filed_under_ak_reads_the_vision_once(self):
        self.assertEqual(self.rulebook({}).count(HEADING), 0)
        other = self.clone("widget", "# widget\n\n## Working here\n\nTests.\n")
        self.assertEqual(self.rulebook({"repo": other}).count(HEADING), 0)
        ak = self.clone("agentkit", (REPO / "AGENTS.md").read_text())
        self.assertEqual(self.rulebook({"repo": ak}).count(HEADING), 1)


if __name__ == "__main__":
    unittest.main()
