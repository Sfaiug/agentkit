"""A Muse launch's receipt follows the registry for the Muse that fired its SessionStart hook,
whichever its hook and its registration come first in.  Only entries that process writes after
its hook count: one a crashed Muse left under a pid reused before the hook, another client's,
and any under that pid once the process is gone move nothing."""

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
        root = Path(tmp.name)
        self.receipt = root / f"muse-launch-{TOKEN}"
        self.receipt.mkdir()
        self.registry = root / "muse/runtime/muse/sessions"
        self.registry.mkdir(parents=True)
        # the hook runs under Muse, pid 4242, under pid 1000; pid 5151 is another client
        self.alive = {4242: BIRTH, 1000: BIRTH, 5151: BIRTH}
        parents = {4242: 1000, 1000: 1}
        self.enterContext(patch.object(config, "STATE", root))
        self.enterContext(patch.object(muse, "sessions", lambda: root / "muse/sessions"))
        self.enterContext(patch.object(muse.os, "getppid", lambda: 4242))
        self.enterContext(patch.object(host, "proc_stat",
                                       lambda pid: host.ProcStat("S", parents[pid], 200, 1)))
        self.enterContext(patch.object(host, "process_identity", lambda pid: self.alive.get(pid)))

    def register(self, session, pid):
        (self.registry / f"{session}.json").write_text(json.dumps({
            "schema_version": 1, "session_id": session, "endpoint_hint": "ms-001122334455.sock",
            "target_eligibility": "message_capable", "process_generation_hint": f"pid={pid}"}))

    def new(self, before, after):
        """Muse's /new: no hook, its entry replaced by the next session's."""
        (self.registry / f"{before}.json").unlink()
        self.register(after, 4242)

    def hook(self):
        muse.started(str(self.receipt), {"session_id": "this-launch"})

    def conversation(self):
        return muse.conversation({"muse_launch": TOKEN})

    def test_a_new_before_the_first_read_is_followed_after_a_hook_first(self):
        self.hook()
        self.register("this-launch", 4242)
        self.new("this-launch", "after-new")
        self.assertEqual(self.conversation(), "after-new")

    def test_a_new_before_the_first_read_is_followed_after_a_registration_first(self):
        self.register("this-launch", 4242)
        self.hook()
        self.new("this-launch", "after-new")
        self.assertEqual(self.conversation(), "after-new")

    def test_only_entries_its_muse_wrote_after_its_hook_count(self):
        self.register("crashed-client", 4242)           # an earlier holder of pid 4242
        self.hook()
        self.register("this-launch", 4242)
        self.register("next-door", 5151)                # another client, in the same directory
        self.assertEqual(self.conversation(), "this-launch")
        (self.registry / "this-launch.json").unlink()   # /new, its next entry not yet written
        self.assertEqual(self.conversation(), "this-launch")
        self.register("after-new", 4242)
        self.assertEqual(self.conversation(), "after-new")
        self.alive[4242] = {**BIRTH, "ticks": 999}      # gone, its pid reused
        self.new("after-new", "recycled")
        self.assertEqual(self.conversation(), "after-new")


if __name__ == "__main__":
    unittest.main()
