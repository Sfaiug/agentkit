"""OpenCode titles use the owned launch's plugin, never tmux input or a real HOME."""

import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, orch, watch
from agentkit.harness import opencode


class OpenCodeTitle(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "AK_NOTIFY_SINK": str(self.root / "notices")}))
        self.seat = {"name": "lagoon", "path": str(self.root), "created": 100,
                     "attached": True, "exited": False, "legacy": False}
        self.fixture = json.loads((REPO / "tests/fixtures/opencode-title-storage.json").read_text())
        self.sid = self.fixture["created"]["data"]["id"]
        self.storage = self.root / "storage.json"
        self.store({self.sid: self.fixture["created"]["data"]})
        config.save_session(self.cfg, "lagoon", "mimo", ["mimo"], {"cwd": str(self.root)})
        opencode.launched("lagoon", self.root, None)
        self.receipt = opencode.path_for(self.record())
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "announce_state"))
        self.keys = []

    def record(self):
        return config.session_records()[self.seat["name"]]

    def store(self, data):
        self.storage.write_text(json.dumps(data))

    def title(self, title, sid=None):
        sid = sid or self.sid
        data = json.loads(self.storage.read_text())
        data[sid] = dict(self.fixture["renamed"]["data"], id=sid, title=title)
        self.store(data)

    def tmux(self, *args, **kwargs):
        if args[0] == "rename-session":
            self.assertEqual(args[2], f"={self.seat['name']}")
            self.seat = dict(self.seat, name=args[-1])
        if args[0] in ("send-keys", "capture-pane"):
            self.keys.append(args)
            self.fail("title sync must never read or type into the owner's composer")
        return 0, ""

    def plugin(self, events=(), mode="accept"):
        """Real plugin, fake API storage and clock: the timer runs once even with no events."""
        driver = r'''
import { pathToFileURL } from "node:url";
import { readFileSync, writeFileSync } from "node:fs";
const plugin = (await import(pathToFileURL(process.argv[1]).href)).default;
const [storage, mode, eventJSON] = process.argv.slice(2);
const events = JSON.parse(eventJSON);
const updates = [];
let tick;
globalThis.setInterval = (fn) => { tick = fn; return { unref() {} }; };
globalThis.clearInterval = () => {};
const read = () => JSON.parse(readFileSync(storage, "utf8"));
const ctx = { session: {
  get: async ({ sessionID }) => {
    if (mode === "unreadable") throw new Error("unreadable");
    return read()[sessionID];
  },
  update: async ({ sessionID, title }) => {
    updates.push({ sessionID, title });
    if (mode === "refuse") throw new Error("refused");
    if (mode === "drop") return;
    const data = read();
    data[sessionID].title = title;
    writeFileSync(storage, JSON.stringify(data));
    if (mode === "changed-request") {
      writeFileSync(process.env.AGENTKIT_OPENCODE_RECEIPT + "/title-request.json",
                    JSON.stringify({title: "estuary", id: "newrequest"}));
    }
  }
}, event: { subscribe: async function* () { yield* events; done(); } } };
let done;
const drained = new Promise((resolve) => { done = resolve; });
const stop = await plugin.setup(ctx);
await drained;
// Drain the setup's read-back before exercising the idle rename timer.
await new Promise((resolve) => setImmediate(resolve));
if (mode !== "changed-request") await tick();
stop();
console.log(JSON.stringify(updates));
'''
        proc = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", driver,
             str(REPO / "hooks/opencode-seat/index.js"), str(self.storage), mode,
             json.dumps(events)], env=dict(os.environ, AGENTKIT_OPENCODE_RECEIPT=str(self.receipt)),
            text=True, capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.splitlines()[-1])

    def prompt(self, sid=None):
        return {"type": "session.inbox.enqueued", "data": {
            "sessionID": sid or self.sid, "item": {"type": "user"}}}

    def renamed(self, title, sid=None):
        # 2.0.14 uses this shape for both owner and generated titles (source fixture).
        return dict(self.fixture["events"][0], data={"sessionID": sid or self.sid, "title": title})

    def bind(self):
        self.plugin([self.prompt()])
        orch.records()
        self.assertTrue(watch.sync_title(self.seat))

    def test_new_seat_waits_for_its_session_and_read_back(self):
        self.assertFalse(watch.sync_title(self.seat))
        self.assertEqual(self.plugin(), [])
        self.assertNotIn("session_title", self.record())
        updates = self.plugin([self.prompt()])
        self.assertEqual(updates, [{"sessionID": self.sid, "title": "lagoon"}])
        self.assertNotIn("session_title", self.record())
        self.assertTrue(watch.sync_title(self.seat))
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.assertEqual(self.keys, [])

    def test_ak_rename_is_recorded_only_after_opencode_has_it(self):
        self.bind()
        orch.rename("lagoon", "quay")
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.assertFalse(watch.sync_title(self.seat))
        self.assertEqual(self.plugin(), [{"sessionID": self.sid, "title": "quay"}])
        self.assertTrue(watch.sync_title(self.seat))
        self.assertEqual(self.record()["session_title"], "quay")
        self.assertEqual(self.plugin(), [])
        self.assertEqual(self.keys, [])

    def test_auto_name_uses_the_same_rename_path(self):
        self.bind()
        config.update_session("lagoon", unnamed=True)
        orch.rename("lagoon", "fix-api", auto=True)
        self.plugin()
        self.assertTrue(watch.sync_title(self.seat))
        self.assertEqual(self.record()["session_title"], "fix-api")
        self.assertNotIn("unnamed", self.record())

    def test_owner_rename_cannot_be_distinguished_and_does_not_rename_seat(self):
        self.bind()
        self.title("quay")
        self.assertIsNone(watch.follow_title(self.seat))
        self.plugin([self.renamed("quay")])
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertEqual(json.loads(self.storage.read_text())[self.sid]["title"], "lagoon")

    def test_automatic_title_never_renames_seat_or_replaces_ak_title(self):
        self.bind()
        self.title("Generated task title")
        self.assertIsNone(watch.follow_title(self.seat))
        self.plugin([self.renamed("Generated task title")])
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertEqual(json.loads(self.storage.read_text())[self.sid]["title"], "lagoon")

    def test_another_sessions_title_changes_nothing(self):
        self.bind()
        self.title("foreign-name", "ses_other")
        self.assertEqual(self.plugin([self.renamed("foreign-name", "ses_other")]), [])
        self.assertIsNone(watch.follow_title(self.seat))
        self.assertEqual(self.seat["name"], "lagoon")
        self.assertEqual(json.loads(self.storage.read_text())["ses_other"]["title"], "foreign-name")
        self.assertEqual(opencode.conversation(self.record()), self.sid)

    def test_successful_call_without_read_back_is_not_confirmation(self):
        for mode in ("drop", "refuse", "unreadable"):
            with self.subTest(mode=mode):
                (self.receipt / "session").write_text(self.sid)
                self.plugin(mode=mode)
                self.assertFalse(watch.sync_title(self.seat))
                self.assertNotIn("session_title", self.record())
        self.plugin()
        self.assertTrue(watch.sync_title(self.seat))

    def test_old_acknowledgement_cannot_confirm_a_reused_name(self):
        self.bind()
        old = (self.receipt / "title-applied.json").read_text()
        orch.rename("lagoon", "quay")
        self.plugin()
        orch.rename("quay", "lagoon")
        (self.receipt / "title-applied.json").write_text(old)
        self.assertFalse(watch.sync_title(self.seat))
        self.plugin()
        self.assertTrue(watch.sync_title(self.seat))

    def test_another_sessions_receipt_cannot_confirm_the_title(self):
        self.bind()
        path = self.receipt / "title-applied.json"
        applied = json.loads(path.read_text())
        path.write_text(json.dumps(dict(applied, sessionID="ses_other")))
        self.assertFalse(watch.sync_title(self.seat))

    def test_subagent_is_not_named_or_claimed(self):
        data = json.loads(self.storage.read_text())
        data[self.sid]["parentID"] = "ses_parent"
        self.store(data)
        self.assertEqual(self.plugin([self.prompt()]), [])
        self.assertIsNone(opencode.conversation(self.record()))
        (self.receipt / "session").write_text(self.sid)
        self.assertEqual(self.plugin(), [])
        self.assertFalse(watch.sync_title(self.seat))

    def test_request_changed_during_update_is_not_acknowledged(self):
        (self.receipt / "session").write_text(self.sid)
        self.plugin(mode="changed-request")
        self.assertFalse((self.receipt / "title-applied.json").exists())
        self.assertNotIn("session_title", self.record())

    def test_resumed_launch_names_existing_session_and_clears_confirmation(self):
        self.bind()
        opencode.launched("lagoon", self.root, self.sid)
        self.assertFalse(self.receipt.exists())
        self.receipt = opencode.path_for(self.record())
        self.assertNotIn("session_title", self.record())
        self.plugin()
        self.assertTrue(watch.sync_title(self.seat))

    def test_removed_launch_is_never_recreated(self):
        self.bind()
        opencode.forget(self.record())
        self.assertFalse(watch.sync_title(self.seat))
        self.plugin([self.prompt()])
        self.assertFalse(self.receipt.exists())


if __name__ == "__main__":
    unittest.main()
