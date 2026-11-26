"""A seat record holding a build or review effort that is no text does not read, so the seat's
`c` says its roles are not shown instead of failing on it.  Black-box: `AK_BIN` as the popup over
an akseat.py seat in an akterm.py terminal, its harnesses fakeadapter.py's; it fails against
`/bin/false`."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RoleEffortIsText(unittest.TestCase):
    def test_a_null_build_or_review_effort_leaves_the_roles_unshown(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        fakeadapter.install(home, claude="pass")
        for role, key in (("workers", "exec_effort"), ("reviewers", "review_effort")):
            with self.subTest(key):
                name = f"acme-{role}"
                Seat(home, name, record={"workers": [], "reviewers": [], role: ["opus"],
                                         "efforts": {"opus": {"effort": "low", key: None}}})
                term = Terminal(home, "attach", "--overlay", size=(100, 30),
                                env={"NO_COLOR": "1", "AGENTKIT_SESSION": name})
                self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane,
                                "sleep 86400", server=SERVER)
                term.wait("esc leave")
                term.keys("c")
                term.wait(lambda screen: "esc back" in screen
                          and "roles are not shown" in " ".join(screen.split()))


if __name__ == "__main__":
    unittest.main()
