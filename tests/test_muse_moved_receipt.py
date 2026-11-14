"""A Muse launch receipt Muse's registry moved on, before a seat followed its own Muse's Stops
instead, still says where the line ak typed before that launch named its session went: the
session it reported, kept as `reported`.  The owner's same words in the session the receipt moved
to are the owner's; the seat reads that one as its own.  Every receipt, log and seat here lives
in a temporary HOME."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import config, harness
from agentkit.harness import muse

TOKEN = "a" * 32
LINE = "Continue the interrupted turn."


class MovedReceipt(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.enterContext(patch.dict(os.environ, {"HOME": str(root), "XDG_DATA_HOME": ""}))
        for name in ("HOME", "STATE", "RUNS", "WT", "WORK", "TMP", "SECRETS", "ENV", "CODE"):
            self.enterContext(patch.object(config, name, root / ".agentkit" / name.lower()))
        config.ensure_dirs()
        config.save_session(config.load(), "lagoon", "spark", ["spark"],
                            {"cwd": str(root), "muse_launch": TOKEN})
        receipt = muse.path_for({"muse_launch": TOKEN})
        receipt.mkdir()
        (receipt / "session").write_text("after-new")
        (receipt / "reported").write_text("before-new")
        for at, session in ((20, "before-new"), (30, "after-new")):
            log = root / f".local/share/muse/sessions/2026/10/24/{session}/session.jsonl"
            log.parent.mkdir(parents=True)
            log.write_text(json.dumps({"recorded_at": at * 1_000_000, "payload": {
                "kind": "run", "event": {"kind": "started", "prompt": LINE}}}) + "\n")
        config.seat_file("input", "lagoon").write_text(json.dumps({
            "at": 10, "text": LINE, "source": "ak", "harness": "muse", "conversation": None,
            "after": 0, "launch": {"muse_launch": TOKEN}}) + "\n")

    def test_the_owner_s_same_words_in_the_session_it_moved_to_are_the_owner_s(self):
        plugin = harness.load("muse")
        record = config.session_records()["lagoon"]
        self.assertEqual(plugin.conversation(record), "after-new")
        self.assertEqual(plugin.went_into({"conversation": None,
                                           "launch": {"muse_launch": TOKEN}}), "before-new")
        self.assertEqual(plugin.user_messages(record, None, "after-new", seat="lagoon"),
                         [{"at": 30, "text": LINE}])


if __name__ == "__main__":
    unittest.main()
