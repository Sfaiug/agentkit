"""A seat renamed any number of times keeps resolving to the name it goes by now.

`ak orch rename` leaves a pointer at the old name, and a seat's title renames it as its
conversation moves on.  Every older name points straight at the newest, so no chain grows
past the renames `config.resolve_session` follows.

Offline: test_v4n's throwaway HOME.
"""

import json
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import config


class RenameChainOneHop(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, "fix-api", "opus", ["opus"], {"cwd": str(self.root)})

    def pointer(self, name):
        return json.loads(config.session_path(name).read_text())

    def test_a_seat_renamed_more_often_than_a_walk_follows_still_resolves(self):
        names = ["fix-api", *(f"fix-api-{n}" for n in range(1, config.RENAME_HOPS + 3))]
        for old, new in zip(names, names[1:]):
            config.rename_session(old, new)
        for name in names[:-1]:
            with self.subTest(name=name):
                self.assertEqual(config.resolve_session(name), names[-1])
                self.assertEqual(self.pointer(name), {"renamed": names[-1]})
        self.assertNotIn("renamed", self.pointer(names[-1]))

    def test_renamed_back_to_its_launch_name_every_other_name_leads_there(self):
        for old, new in (("fix-api", "ship-api"), ("ship-api", "deploy-api"),
                         ("deploy-api", "fix-api")):
            config.rename_session(old, new)
        self.assertNotIn("renamed", self.pointer("fix-api"))
        for name in ("ship-api", "deploy-api"):
            with self.subTest(name=name):
                self.assertEqual(self.pointer(name), {"renamed": "fix-api"})

    def test_another_seats_pointers_stay_as_they_are(self):
        config.save_session(self.cfg, "other-api", "opus", ["opus"], {"cwd": str(self.root)})
        config.rename_session("other-api", "other-api-2")
        config.rename_session("fix-api", "fix-api-2")
        config.rename_session("fix-api-2", "fix-api-3")
        self.assertEqual(self.pointer("other-api"), {"renamed": "other-api-2"})
        self.assertEqual(self.pointer("fix-api"), {"renamed": "fix-api-3"})


if __name__ == "__main__":
    unittest.main()
