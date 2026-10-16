"""Real Stop hook and detached reader, with model, meters and delivery stubbed offline."""

import json
import os
import subprocess
import sys
import time
import unittest

import test_stop_hook as stops

QUESTION = "Which schema should acme use?"
SAID = "Both schemas work.\n\n" + QUESTION

# Loaded in both the hook and its detached process, never in the owner's HOME.
STUB = '''import json, os, time
from pathlib import Path
from agentkit import config, notify, prose, staffing, usage, watch, worker
root = Path(os.environ["HOME"])
watch.start_look = lambda *_a, **_kw: None
staffing.collect_usage = lambda *_a, **_kw: {}
staffing.ready_order = lambda *_a, **_kw: json.loads((root / "order").read_text())
usage.account = lambda *_a, **_kw: (None, None)
config.model = lambda *_a, **_kw: {"provider": "acme"}
def turn(cfg, model, body, workspace, out_dir, **kw):
    with (root / "calls").open("a") as log:
        log.write(json.dumps({"model": model, "body": body, "role": kw["role"]}) + "\\n")
    while (root / "hold").exists():
        time.sleep(.01)
    result = json.loads((root / "answer").read_text())
    if result.get("raises"):
        raise RuntimeError("model unavailable")
    return result.get("code", 0), result["text"], "", result.get("killed", False), False
worker.turn = turn
def transition(name, **_kw):
    (root / "sent").write_text(json.dumps(notify.last(name)))
    return 0
notify.transition = transition
original = prose.catch
def catch(*args):
    try:
        original(*args)
    finally:
        (root / "finished").touch()
prose.catch = catch
'''


class ProseQuestionCaught(stops.StopHook):
    def setUp(self):
        super().setUp()
        (self.home / "sitecustomize.py").write_text(STUB)
        (self.state / f"session-{stops.SEAT}.json").write_text(json.dumps(
            {"orchestrator": "acme-model", "workers": ["acme-model"]}))
        self.order = self.home / "order"
        self.order.write_text(json.dumps(["acme-model"]))
        self.answer(question=QUESTION)
        # No work owed: the real hook allows this turn to end on its first Stop.
        (self.state / f"plan-{stops.SEAT}.md").unlink()
        self.addCleanup(self.finish_reader)

    def answer(self, *, question=None, text=None, **fields):
        (self.home / "answer").write_text(json.dumps(
            {"text": json.dumps({"question": question}) if text is None else text, **fields}))

    def wait_for(self, name):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if (self.home / name).exists():
                return
            time.sleep(.01)
        self.fail(f"detached reader did not write {name}")

    def finish_reader(self):
        (self.home / "hold").unlink(missing_ok=True)
        latch = json.loads((self.state / f"stop-{stops.SEAT}.json").read_text())
        if latch.get("prose"):
            self.wait_for("finished")

    def needs(self):
        path = self.state / f"notify-{stops.SEAT}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def test_open_question_is_recorded_sent_and_answered(self):
        self.assertEqual(self.stop(SAID), "")
        self.wait_for("finished")
        self.assertEqual((self.needs()["kind"], self.needs()["text"]), ("needs", QUESTION))
        self.assertEqual(json.loads((self.home / "sent").read_text())["text"], QUESTION)
        call = json.loads((self.home / "calls").read_text())
        self.assertEqual((call["model"], call["role"]), ("acme-model", "reader"))
        self.assertIn(SAID, call["body"])
        env = {**os.environ, "HOME": str(self.home), "PYTHONPATH": f"{self.home}:{stops.REPO}"}
        subprocess.run([sys.executable, "-c", "import time; from agentkit import notify; "
                        f"notify.answered({stops.SEAT!r}, time.time() + 1)"],
                       env=env, check=True, capture_output=True, timeout=15)
        self.assertIn("answered_at", self.needs())

    def test_no_open_question_records_nothing_and_turn_is_read_once(self):
        self.answer()
        self.assertEqual(self.stop("The parser is fixed."), "")
        self.wait_for("finished")
        self.assertIsNone(self.needs())
        self.assertFalse((self.home / "sent").exists())
        self.assertEqual(self.stop("The parser is fixed."), "")
        self.assertEqual(len((self.home / "calls").read_text().splitlines()), 1)

    def test_recorded_question_and_held_or_background_stops_make_no_call(self):
        self.notified("needs", self.turn + 1)
        self.assertEqual(self.stop(SAID), "")
        self.assertFalse((self.home / "calls").exists())
        (self.state / f"notify-{stops.SEAT}.json").unlink()
        (self.state / f"plan-{stops.SEAT}.md").write_text(stops.OWED)
        self.assertEqual(self.blocked(self.stop(SAID))["decision"], "block")
        self.assertEqual(self.stop(SAID, background_tasks=[{"type": "command"}]), "")
        self.assertFalse((self.home / "calls").exists())
        self.assertFalse(json.loads((self.state / f"stop-{stops.SEAT}.json").read_text()).get("prose"))

    def test_harness_question_even_answered_makes_no_call(self):
        before = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "q1", "name": "AskUserQuestion"}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "q1", "content": "v2"}]}}]
        transcript = self.transcript(SAID, before=before)
        self.assertEqual(self.stop(transcript_path=str(transcript)), "")
        self.assertFalse((self.home / "calls").exists())

    def test_worker_makes_no_call(self):
        self.assertEqual(self.stop(SAID, env={"AK_RUN_ROLE": "worker"}), "")
        self.assertFalse((self.home / "calls").exists())

    def test_payload_message_is_read_whole_without_an_argument_size_limit(self):
        said = "Context. " * 20000 + "\n" + QUESTION
        self.assertEqual(self.stop(None, lastAssistantMessage=said), "")
        self.wait_for("finished")
        self.assertEqual(self.needs()["text"], QUESTION)
        self.assertIn(said, json.loads((self.home / "calls").read_text())["body"])

    def test_kept_question_makes_no_call(self):
        path = self.state / f"seat-{stops.SEAT}.json"
        path.write_text(json.dumps({"unasked": {"text": QUESTION}}))
        self.assertEqual(self.stop(SAID), "")
        self.assertFalse(json.loads((self.state / f"stop-{stops.SEAT}.json").read_text()).get("prose"))

    def test_question_recorded_during_model_call_is_kept(self):
        (self.home / "hold").touch()
        self.assertEqual(self.stop(SAID), "")
        self.wait_for("calls")
        self.notified("needs", self.turn + 1)
        (self.home / "hold").unlink()
        self.wait_for("finished")
        self.assertEqual(self.needs()["text"], "something")
        self.assertFalse((self.home / "sent").exists())

    def test_hook_returns_while_model_is_waiting_and_new_turn_discards_result(self):
        (self.home / "hold").touch()
        self.assertEqual(self.stop(SAID), "")
        self.wait_for("calls")
        self.latch(self.turn + 30)
        (self.home / "hold").unlink()
        self.wait_for("finished")
        self.assertIsNone(self.needs())

    def test_failed_unavailable_and_malformed_calls_log_once_and_record_nothing(self):
        for result in ({"code": 1}, {"killed": True}, {"text": "not JSON"}, {"raises": True},
                       {"question": "An invented question?"}, {"unavailable": True}):
            with self.subTest(result=result):
                self.latch(self.turn)
                (self.home / "finished").unlink(missing_ok=True)
                if result.pop("unavailable", False):
                    self.order.write_text("[]")
                else:
                    self.answer(**result)
                self.assertEqual(self.stop(SAID), "")
                self.wait_for("finished")
                self.assertIsNone(self.needs())
        self.assertEqual(len((self.state / f"log-{stops.SEAT}.txt").read_text().splitlines()), 6)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(ProseQuestionCaught(name) for name in ProseQuestionCaught.__dict__
                              if name.startswith("test_"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
