"""A seat's hooks start no git when it starts, is told a notice and ends a turn.

Each of them once read the seat's project's numbers from git before doing its work, for a help
text it never printed, and a done seat's Stop later read its project's test-times record through
git before looking at history: on a loaded host, seconds of every hook a seat fired.  Black-box:
the hooks the adapter beside the program `AK_BIN` names registers fire from outside through
tests/fixtures/hookdrive.py, with a `git` that writes down each call.
"""

from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REFUSE, Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig
from fixtures.hookdrive import Hooks, transcript


class ASeatsHooksStartNoGit(unittest.TestCase):
    def test_no_hook_of_a_seat_at_rest_calls_git(self):
        with Home() as home:
            rig = Rig(home, "acme", files={
                "AGENTS.md": "---\ntests: bash tests/all.sh\nhealth: none\nusers: none\n---\n"})
            seat = Seat(home, "acme", cwd=rig.path, record={"repo": str(rig.path)})
            home.write(".agentkit/state/plan-acme.md",
                       "- [x] the api answers · check: `true` · acme · written 2026-11-18 10:00"
                       " · done 0123456789ab\n")
            hooks = Hooks(home)
            fired = hooks.fire("UserPromptSubmit", {"prompt": "go", "session_id": "conv-acme"},
                               seat="acme", pane=seat, finished=True)
            self.assertEqual(fired.code, 0, fired.err)
            home.fake("git", REFUSE.format(python=shlex.quote(sys.executable), name="git",
                                           log=shlex.quote(str(home.log("git")))))
            events = {"SessionStart": {"source": "startup"}, "Notification": {"message": "acme"},
                      "Stop": {"background_tasks": [],
                               "transcript_path": transcript(home, "acme", "Done.")}}
            for event, payload in events.items():
                with self.subTest(event=event):
                    fired = hooks.fire(event, payload, seat="acme", pane=seat, finished=True)
                    self.assertEqual(fired.code, 0, fired.err)
                    self.assertEqual(home.calls("git"), [])


if __name__ == "__main__":
    unittest.main()
