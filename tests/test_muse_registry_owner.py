"""A Muse launch's receipt follows the registry only for the Muse bound to it: the process of
its hook's lineage the registry listed holding the receipt's own session, alive as it was.  An
entry a crashed Muse left under a pid reused before the hook, another client's entry, and an
entry under the bound pid once that process is gone move nothing."""

import json
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import config, host
from agentkit.harness import muse

TOKEN = "a" * 32
BIRTH = {"boot": "fake-boot", "ticks": 200, "started_at": 200.0}


class RegistryOwner(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.receipt = self.root / f"muse-launch-{TOKEN}"
        self.receipt.mkdir()
        (self.receipt / "session").write_text("this-launch")
        (self.receipt / "lineage").write_text(json.dumps([[4242, BIRTH], [1000, BIRTH]]))
        self.registry = self.root / "muse/runtime/muse/sessions"
        self.registry.mkdir(parents=True)
        self.alive = {4242: BIRTH, 1000: BIRTH, 5151: BIRTH}
        self.enterContext(patch.object(config, "STATE", self.root))
        self.enterContext(patch.object(muse, "sessions", lambda: self.root / "muse/sessions"))
        self.enterContext(patch.object(host, "process_identity", lambda pid: self.alive.get(pid)))

    def register(self, session, pid):
        (self.registry / f"{session}.json").write_text(json.dumps({
            "schema_version": 1, "session_id": session, "endpoint_hint": "ms-001122334455.sock",
            "target_eligibility": "message_capable", "process_generation_hint": f"pid={pid}"}))

    def conversation(self):
        return muse.conversation({"muse_launch": TOKEN})

    def test_an_entry_left_under_a_pid_reused_before_the_hook_is_not_this_launch(self):
        self.register("other-launch", 4242)
        self.assertEqual(self.conversation(), "this-launch")

    def test_the_bound_muse_is_followed_and_kept_alone(self):
        self.register("this-launch", 4242)
        self.register("next-door", 5151)               # another client's, in the same directory
        self.assertEqual(self.conversation(), "this-launch")
        (self.registry / "this-launch.json").unlink()  # /new
        self.register("after-new", 4242)
        self.assertEqual(self.conversation(), "after-new")
        self.alive[4242] = {**BIRTH, "ticks": 999}     # gone, its pid reused
        self.register("recycled", 4242)
        (self.registry / "after-new.json").unlink()
        self.assertEqual(self.conversation(), "after-new")


if __name__ == "__main__":
    unittest.main()
