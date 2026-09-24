"""Finding 3: seat ownership regression. Offline; all state and fake harnesses stay here."""

from contextlib import ExitStack, redirect_stdout
from datetime import datetime
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, terminal, usage
from agentkit.harness import codex as codex_plugin


class Ownership(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".codex-seat-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "CODEX_HOME": str(self.root / ".codex"),
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(self.root / "sockets"),
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1"}))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        config.ensure_dirs()
        self.cwd = self.root / "shared cwd"
        self.cwd.mkdir()
        (self.root / ".codex").mkdir()
        (self.root / "sockets").mkdir(mode=0o700)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {"PATH": f"{self.bin}:{os.environ['PATH']}"}))
        # No real tmux invocation is needed. The stand-in refuses every other socket.
        self.fake("tmux", '''import sys
assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv
''')
        self.fake("codex", '''import json, os, pathlib, shlex, subprocess, sys, tomllib
a = sys.argv[1:]
if a == ["--help"]:
    print("--dangerously-bypass-hook-trust" if not os.environ.get("FAKE_UNSUPPORTED") else "old CLI")
    sys.exit(0)
assert "AGENTKIT_CODEX_RECEIPT" not in os.environ
assert "--dangerously-bypass-hook-trust" not in a
p = pathlib.Path.home()
sid = a[a.index("resume") + 1] if "resume" in a else os.environ["FAKE_THREAD"]
(p / "last-command.json").write_text(json.dumps(a))
path = p / ".codex" / "sessions" / ("rollout-" + sid + ".jsonl")
path.parent.mkdir(exist_ok=True)
if not path.exists():
    path.write_text(json.dumps({"type": "session_meta", "payload": {
        "id": sid, "cwd": os.getcwd(), "timestamp": os.environ.get("FAKE_STAMP", "2026-09-11T08:00:00Z")}}) + "\\n")
event = {"session_id": sid, "transcript_path": str(path), "cwd": os.getcwd(),
         "hook_event_name": "SessionStart", "source": "resume" if "resume" in a else "startup"}
for arg in a:
    if arg.startswith("hooks.SessionStart=") and not os.environ.get("FAKE_UNTRUSTED"):
        groups = tomllib.loads(arg)["hooks"]["SessionStart"]
        for group in groups:
            for hook in group["hooks"]:
                subprocess.run(shlex.split(hook["command"]), input=json.dumps(event), text=True, check=True)
''')
        adapters = self.root / "adapters"
        adapters.mkdir()
        for harness in ("claude", "codex", "muse"):
            path = adapters / f"{harness}.sh"
            if harness == "codex":
                path.write_text('#!/bin/sh\n[ "$1" = interactive ] || exit 97\n'
                                f'exec {shlex.quote(str(REPO / "adapters/codex.sh"))} "$@"\n')
            else:
                path.write_text('#!/bin/sh\n[ "$1" = interactive ] || exit 97\necho true\n')
            path.chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        self.cfg = config.load()
        self.seats = []
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: self.seats))
        self.stack.enter_context(patch.object(orch, "attach", return_value=0))
        self.stack.enter_context(patch.object(usage, "collect", return_value={}))
        self.stack.enter_context(patch.object(orch, "start", side_effect=self.start))
        self.stack.enter_context(patch.object(orch, "dress"))
        self.stack.enter_context(patch.object(orch.time, "time", return_value=100))

    def fake(self, name, script):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + script)
        path.chmod(0o755)

    def start(self, name, cwd, cmd, model, resumable=True):
        record = config.session_records()[name]
        if model == "astra":
            self.assertTrue(codex_plugin.path_for(record).exists())
        subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)

    def create(self, name, sid, **env):
        with patch.dict(os.environ, {"FAKE_THREAD": sid, **env}), redirect_stdout(io.StringIO()):
            orch.create(self.cfg, name, self.cwd, forced="astra", forced_workers="opus")
        return orch.records()[name]

    def rollout(self, sid, stamp="2026-09-11T09:00:00Z", cwd=None):
        path = self.root / ".codex/sessions" / f"rollout-{sid}.jsonl"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": sid, "cwd": str(cwd or self.cwd), "timestamp": stamp}}) + "\n")
        return path

    def resume(self, name):
        logs = []
        with patch.dict(os.environ, {"FAKE_THREAD": "fresh-thread"}):
            orch.resume(self.cfg, name, log=logs.append)
        return json.loads((self.root / "last-command.json").read_text()), logs

    def test_interleaved_seats_and_same_second_launches_never_cross(self):
        base = datetime.fromisoformat("2026-09-11T08:00:00+00:00").timestamp()
        for simultaneous in (False, True):
            with self.subTest(simultaneous=simultaneous):
                a, b = f"alpha-{int(simultaneous)}", f"beta-{int(simultaneous)}"
                with patch.object(orch.time, "time", return_value=base):
                    alpha = self.create(a, a, FAKE_STAMP="2026-09-11T08:00:00Z" if simultaneous
                                        else "2026-09-11T08:01:00Z")
                with patch.object(orch.time, "time", return_value=base if simultaneous else base + 120):
                    beta = self.create(b, b, FAKE_STAMP="2026-09-11T08:00:00Z" if simultaneous
                                       else "2026-09-11T08:03:00Z")
                self.assertEqual(alpha["created"] == beta["created"], simultaneous)
                self.assertNotEqual(alpha["codex_launch"], beta["codex_launch"])
                self.rollout("unrelated-latest")
                for name in (a, b, a, b):
                    args, logs = self.resume(name)
                    self.assertEqual(args[args.index("resume") + 1], name)
                    self.assertIn(f"conversation {name}", logs[0])
                    record = orch.records()[name]
                    self.assertEqual(record["conversation"], name)
                    self.assertEqual(record["id_source"], codex_plugin.SOURCE)

    def test_legacy_zero_one_many_rollouts_preserve_data_and_start_fresh(self):
        for count in (0, 1, 2):
            with self.subTest(count=count):
                for path in (self.root / ".codex/sessions").glob("rollout-*.jsonl"):
                    path.unlink()
                name = f"legacy-{count}"
                original = {"cwd": str(self.cwd), "created": 100, "conversation": "old-guess",
                            "id_source": "discovered", "resumable": True, "before": ["old-data"]}
                config.save_session(self.cfg, name, "astra", ["opus"], original)
                for i in range(count):
                    self.rollout(f"candidate-{i}")
                record = orch.records()[name]
                self.assertFalse(record["resumable"])
                for key in ("conversation", "id_source", "before"):
                    self.assertEqual(record[key], original[key])
                self.assertIsNone(orch.seat_conversation(record))
                row = next(s for s in orch.listing() if s["name"] == name)
                # nobody is in it: the row says so, and its number is the way back in
                self.assertEqual(menu.state(row), "needs you")
                self.assertIn("ownership unverified", menu.row(self.cfg, 1, row)[4])
                for width in (40, 100):
                    with patch.object(terminal, "width", return_value=width), \
                            redirect_stdout(io.StringIO()) as output:
                        menu.draw(self.cfg, [row])
                    # A gone seat with a conversation to resume into keeps its row, and
                    # its reason says what the number will do -- whole where it fits.
                    self.assertIn("session closed: press 1 to reopen", output.getvalue())
                    if width == 100:
                        self.assertRegex(output.getvalue(), r"starts\s+fresh")
                    self.assertTrue(all(terminal.cells(line) <= width
                                        for line in output.getvalue().splitlines()))
                with patch.object(orch, "resume", return_value=0) as resume:
                    menu.open_session(self.cfg, row, False)
                    resume.assert_called_once()
                args, logs = self.resume(name)
                self.assertNotIn("resume", args)
                self.assertIn("ownership unverified; it starts fresh", logs[0])
                saved = config.session_records()[name]
                self.assertEqual(saved["codex_history"][0]["conversation"], "old-guess")
                self.assertEqual(saved["before"], ["old-data"])

    def test_missing_malformed_and_conflicting_metadata_never_falls_back(self):
        for kind in ("missing", "partial", "wrong-id", "wrong-cwd", "stale-id", "stale-launch",
                     "malformed-receipt", "conflicting-hook"):
            with self.subTest(kind=kind):
                name = "seat-" + kind
                record = self.create(name, name)
                receipt = codex_plugin.read(record)
                path = Path(receipt["event"]["transcript_path"])
                if kind == "missing":
                    path.unlink()
                elif kind == "partial":
                    path.write_text('{"type":')
                elif kind in ("wrong-id", "wrong-cwd"):
                    data = json.loads(path.read_text())
                    data["payload"]["id" if kind == "wrong-id" else "cwd"] = "unrelated"
                    path.write_text(json.dumps(data))
                elif kind == "stale-id":
                    config.update_session(name, conversation="unrelated")
                elif kind == "stale-launch":
                    receipt["launch"] = "0" * 32
                    codex_plugin.path_for(record).write_text(json.dumps(receipt))
                elif kind == "malformed-receipt":
                    codex_plugin.path_for(record).write_text("[]")
                else:
                    codex_plugin.capture(codex_plugin.path_for(record),
                                       {**receipt["event"], "session_id": "unrelated"})
                self.rollout("later-unrelated")
                self.assertIsNone(orch.seat_conversation(orch.records()[name]))
                args, _ = self.resume(name)
                self.assertNotIn("resume", args)

    def test_rename_exit_stop_and_late_hook(self):
        record = self.create("old", "owned")
        receipt_path = codex_plugin.path_for(record)
        event = codex_plugin.read(record)["event"]
        self.seats = [{"name": "old", "exited": True, "created": 100,
                       "path": str(self.cwd), "resumable": False}]
        self.assertEqual(menu.state(orch.listing()[0]), "needs you")
        # Actual tmux command construction reaches only the isolated socket stand-in.
        orch.rename("old", "renamed")
        self.seats[0]["name"] = "renamed"
        codex_plugin.capture(receipt_path, event)
        self.assertEqual(orch.records()["renamed"]["conversation"], "owned")
        with patch.object(orch, "tmux_out", return_value=(0, "")) as tmux:
            args, _ = self.resume("renamed")
            respawn = next(c for c in tmux.call_args_list if c.args[0] == "respawn-pane")
            self.assertEqual(respawn.kwargs["socket"], "agentkit-test")
            self.assertIn("resume owned", respawn.args[-1])
        self.seats = []
        args, _ = self.resume("renamed")
        self.assertEqual(args[args.index("resume") + 1], "owned")
        receipt_path = codex_plugin.path_for(orch.records()["renamed"])
        with redirect_stdout(io.StringIO()):
            orch.cmd_stop(["old"])
        codex_plugin.capture(receipt_path, event)
        self.assertFalse(receipt_path.exists())
        self.assertEqual(orch.listing(), [])
        self.assertEqual(config.session_aliases(), {})
        new = self.create("old", "replacement")
        self.assertEqual(orch.seat_conversation(new), "replacement")

    def test_unsupported_capture_and_stale_callback(self):
        record = self.create("unsupported", "real-unbound", FAKE_UNSUPPORTED="1")
        self.assertFalse(record["resumable"])
        old_path = codex_plugin.path_for(record)
        self.rollout("unrelated")
        args, _ = self.resume("unsupported")
        self.assertNotIn("resume", args)
        codex_plugin.capture(old_path, {"hook_event_name": "SessionStart", "source": "startup",
                                    "session_id": "real-unbound", "cwd": str(self.cwd),
                                    "transcript_path": str(self.rollout("real-unbound"))})
        self.assertFalse(old_path.exists())
        self.assertEqual(orch.records()["unsupported"]["conversation"], "fresh-thread")

    def test_hook_trust_is_preserved_and_definition_is_stable(self):
        record = self.create("untrusted", "untrusted-thread", FAKE_UNTRUSTED="1")
        self.assertFalse(record["resumable"])
        self.assertEqual(menu.state(orch.listing()[0]), "needs you")
        before = json.loads((self.root / "last-command.json").read_text())
        after, _ = self.resume("untrusted")
        self.assertEqual([a for a in before if a.startswith("hooks.SessionStart=")],
                         [a for a in after if a.startswith("hooks.SessionStart=")])
        self.assertEqual(orch.records()["untrusted"]["conversation"], "fresh-thread")

    def test_unbound_without_an_old_id_and_changed_session_in_one_launch(self):
        config.save_session(self.cfg, "unbound", "astra", ["opus"],
                            {"cwd": str(self.cwd), "created": 100})
        self.rollout("only-candidate")
        self.assertIsNone(orch.seat_conversation(orch.records()["unbound"]))
        self.assertFalse(orch.listing()[0]["resumable"])
        record = self.create("used", "first-owned")
        event = codex_plugin.read(record)["event"]
        # A harmless compaction retains ownership. A new conversation in this launch is
        # ambiguous, even though both rollouts have matching cwd and qualifying timestamps.
        codex_plugin.capture(codex_plugin.path_for(record), {**event, "source": "compact"})
        self.assertEqual(orch.seat_conversation(record), "first-owned")
        second = self.rollout("second-owned")
        codex_plugin.capture(codex_plugin.path_for(record),
                           {**event, "source": "clear", "session_id": "second-owned",
                            "transcript_path": str(second)})
        self.assertIsNone(orch.seat_conversation(record))
        self.assertFalse(orch.records()["used"]["resumable"])

    def test_sweep_removes_receipt_but_keeps_the_transcript(self):
        record = self.create("swept", "saved")
        receipt_path = codex_plugin.path_for(record)
        event = codex_plugin.read(record)["event"]
        config.update_session("swept", seen=1)
        with patch.object(orch.time, "time", return_value=config.SESSION_STALE + 2), \
                patch.object(orch, "tmux_out", return_value=(1, "no server running on fixture socket")):
            orch.sweep(lambda _: None)
        codex_plugin.capture(receipt_path, event)
        self.assertFalse(receipt_path.exists())
        self.assertTrue(Path(event["transcript_path"]).exists())
        self.assertEqual(orch.listing(), [])

    def test_other_harnesses_keep_their_launch_contract(self):
        for model in ("fable", "spark"):
            name = "other-" + model
            config.save_session(self.cfg, name, model, ["opus"], {"cwd": str(self.cwd)})
            with patch.object(orch, "start"):
                orch.launch(name, model, self.cwd, ["true"], "pinned" if model == "fable" else None)
            record = orch.records()[name]
            self.assertNotIn("codex_launch", record)
            self.assertEqual(orch.resumable(record), model == "fable")


if __name__ == "__main__":
    unittest.main()
