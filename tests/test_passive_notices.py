"""A notice with no manifest state leaves the last turn fact and typing gate alone.

Both hooks run against a temporary HOME, with real captured panes and no live seat.
A paused notice also proves it cannot put an earlier fact back over either hook's Stop.
"""

from datetime import datetime
import json
import os
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, watch

SEAT = "fix-api"
FIX = REPO / "tests/fixtures"
PROMPT = (FIX / "claude-prompt-pane.txt").read_text(encoding="utf-8")
QUESTION = (FIX / "claude-question-with-message-pane.txt").read_text(encoding="utf-8")
PASSIVE = ("agent_completed", "push_notification", "elicitation_complete",
           "elicitation_response", "auth_success", "computer_use_exit")


class PassiveNotices(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        home = self.root / ".agentkit"
        home.mkdir()
        (home / "state").symlink_to(config.STATE)
        self.seat = {"name": SEAT, "attached": False}
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.root),
                    "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"}

    def hook(self, event, script="seat-state.sh", env=None, **payload):
        done = subprocess.run(
            ["bash", str(REPO / "hooks" / script)], text=True, capture_output=True,
            input=json.dumps({"hook_event_name": event, **payload}),
            env=self.env if env is None else env, timeout=20)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "")
        path = config.hook_facts_path(self.seat["name"])
        return path.read_bytes() if path.exists() else None

    def asked(self):
        """The question this turn ends on, asked as a seat must: `ak notify needs`, recorded."""
        # the hook reads the real clock; this sandbox's time.time() is a fixed fake
        config.notify_path(SEAT).write_text(json.dumps({
            "session": SEAT, "kind": "needs", "time": datetime.now().timestamp(),
            "text": "Which schema should acme use?"}))

    def looked(self, pane=PROMPT):
        live = watch.live_state(self.seat, "claude", pane=pane, cfg=self.cfg)
        word = watch.session_state(
            self.seat["name"], session=self.seat, cfg=self.cfg, records=[], live=live,
            harness="claude", auth_out={}, gh_out={}, token_out={}, previous={})["word"]
        with patch.object(watch, "pane_text", return_value=pane):
            return word, watch.at_prompt(self.seat, cfg=self.cfg)

    def unchanged(self, before, answer, pane=PROMPT):
        for kind in PASSIVE:
            with self.subTest(kind=kind):
                self.assertEqual(self.hook("Notification", notification_type=kind,
                                           message="A background notice."), before)
                self.assertEqual(self.looked(pane), answer)

    def test_a_running_turn_survives_every_passive_notice(self):
        before = self.hook("UserPromptSubmit", prompt="Build the parser.")
        self.assertEqual(self.looked(), ("working", False))
        self.unchanged(before, ("working", False))

    def test_a_question_and_its_answered_turn_survive_notices(self):
        self.hook("UserPromptSubmit", prompt="Build the parser.")
        before = self.hook("Notification", notification_type="permission_prompt")
        self.unchanged(before, ("needs you", False), QUESTION)
        self.unchanged(before, ("working", False))

    def test_both_hooks_stops_and_an_idle_prompt_stay_free(self):
        for script in ("seat-state.sh", "orchestrator-stop.sh"):
            with self.subTest(script=script):
                self.hook("UserPromptSubmit", prompt="Build the parser.")
                self.asked()
                payload = {"background_tasks": []} if script == "orchestrator-stop.sh" else {}
                before = self.hook("Stop", script=script,
                                   last_assistant_message="Which schema should acme use?", **payload)
                self.assertEqual(set(json.loads(before)), {"session", "event", "kind", "text", "at"})
                self.unchanged(before, ("needs you", True))
        self.hook("UserPromptSubmit", prompt="Build the parser.")
        before = self.hook("Notification", notification_type="idle_prompt")
        self.unchanged(before, ("needs you", True))

    def test_a_notice_needs_neither_a_prior_record_nor_a_known_event_name(self):
        self.assertIsNone(self.hook("Notification", notification_type=PASSIVE[0]))
        self.assertIsNone(self.hook("UnmappedEvent"))
        before = self.hook("UserPromptSubmit")
        self.assertEqual(self.hook("UnmappedEvent"), before)
        self.assertEqual(self.looked(), ("working", False))

    def test_a_seat_with_no_record_still_writes_its_notices(self):
        config.session_path(SEAT).unlink()
        for kind in ("permission_prompt", PASSIVE[0]):
            with self.subTest(kind=kind):
                fact = json.loads(self.hook("Notification", notification_type=kind))
                self.assertEqual((fact["event"], fact["kind"]), ("Notification", kind))

    def test_an_unreadable_manifest_still_writes_the_notice(self):
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "claude.toml").write_text("[hooks\n")
        fact = json.loads(self.hook(
            "Notification", notification_type=PASSIVE[0],
            env={**self.env, config.ADAPTER_DIR_ENV: str(adapters)}))
        self.assertEqual((fact["event"], fact["kind"]), ("Notification", PASSIVE[0]))

    def test_a_failed_classifier_still_writes_the_notice(self):
        bindir = self.root / "bin"
        bindir.mkdir()
        python = bindir / "python3"
        python.write_text('''#!/bin/bash
if [[ ${1:-} = -c && ${2:-} = *watch.hook_state* ]]; then
  exit "$CHECK_STATUS"
fi
exec "$REAL_PYTHON" "$@"
''')
        python.chmod(0o755)
        env = {**self.env, "PATH": f"{bindir}:{self.env['PATH']}",
               "REAL_PYTHON": shutil.which("python3")}
        for status in (1, 2, 127, 137):
            with self.subTest(status=status):
                self.hook("UserPromptSubmit")
                fact = json.loads(self.hook(
                    "Notification", notification_type=PASSIVE[0],
                    env={**env, "CHECK_STATUS": str(status)}))
                self.assertEqual((fact["event"], fact["kind"]), ("Notification", PASSIVE[0]))

    def test_a_renamed_seat_keeps_its_launch_names_hook_fact(self):
        self.hook("UserPromptSubmit")
        config.rename_session(SEAT, "acme")
        self.seat["name"] = "acme"
        before = config.hook_facts_path("acme").read_bytes()
        self.unchanged(before, ("working", False))
        self.assertFalse((config.STATE / f"hook-{SEAT}.json").exists())

    def test_the_manifest_alone_decides_whether_a_notice_is_passive(self):
        before = self.hook("UserPromptSubmit")
        self.assertEqual(self.hook("Notification", notification_type=PASSIVE[0]), before)
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "claude.toml").write_text(
            (REPO / "adapters/claude.toml").read_text() +
            '\n[[hooks.event]]\nname = "Notification"\nstate = "at_prompt"\n'
            'kinds = ["agent_completed"]\n')
        with patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}):
            after = self.hook("Notification", notification_type=PASSIVE[0],
                              env={**self.env, config.ADAPTER_DIR_ENV: str(adapters)})
            self.assertNotEqual(after, before)
            self.assertEqual(self.looked(), ("needs you", True))

    def test_a_paused_notice_never_restores_a_fact_over_a_new_stop_or_prompt(self):
        bindir = self.root / "bin"
        bindir.mkdir()
        ready, release = self.root / "ready", self.root / "release"
        python = bindir / "python3"
        python.write_text('''#!/bin/bash
if [[ ${1:-} = -c && ${2:-} = *watch.hook_state* ]]; then
  "$REAL_PYTHON" "$@"
  status=$?
  : > "$QUERY_READY"
  for ((attempt=0; attempt<500; attempt++)); do
    [[ -f $QUERY_RELEASE ]] && break
    sleep 0.01
  done
  exit "$status"
fi
exec "$REAL_PYTHON" "$@"
''')
        python.chmod(0o755)
        env = {**self.env, "PATH": f"{bindir}:{self.env['PATH']}",
               "REAL_PYTHON": shutil.which("python3"),
               "QUERY_READY": str(ready), "QUERY_RELEASE": str(release)}
        for event, script in (("Stop", "seat-state.sh"), ("Stop", "orchestrator-stop.sh"),
                              ("UserPromptSubmit", "seat-state.sh")):
            with self.subTest(event=event, script=script):
                ready.unlink(missing_ok=True)
                release.unlink(missing_ok=True)
                config.notify_path(SEAT).unlink(missing_ok=True)    # no question standing yet
                self.hook("UserPromptSubmit")
                proc = subprocess.Popen(
                    ["bash", str(REPO / "hooks/seat-state.sh")], env=env, text=True,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    proc.stdin.write(json.dumps({"hook_event_name": "Notification",
                                                 "notification_type": PASSIVE[0]}))
                    proc.stdin.close()
                    proc.stdin = None
                    deadline = time.monotonic() + 10
                    while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(ready.exists(), "the notice never asked the manifest")
                    if event == "Stop":
                        self.asked()    # a newer prompt asks nothing: it would be his answer
                    payload = {"background_tasks": []} if script == "orchestrator-stop.sh" else {}
                    newer = self.hook(event, script=script,
                                      last_assistant_message="Which schema should acme use?", **payload)
                finally:
                    release.touch()
                    out, err = proc.communicate(timeout=20)
                self.assertEqual((proc.returncode, out, err), (0, "", ""))
                self.assertEqual(config.hook_facts_path(SEAT).read_bytes(), newer)
                self.assertEqual(self.looked(), ("needs you", True) if event == "Stop"
                                 else ("working", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
