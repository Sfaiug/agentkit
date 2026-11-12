"""An effort set inside a Muse seat reaches its bar and record at its next model call.

Muse 1.4.15 logs only that `/effort` ran, naming no level; each model call names the effort it
runs at, to the PreLLMCall hook a seat's launch carries where its muse's schema names that hook
(`"preLLMCall"`).  An answer names no effort, so one on the same model landing after the call
leaves the call's effort standing.  The reminders Muse runs around a turn call under sessions of
their own, which have no log of their own, at efforts of their own: those move nothing.

Black-box against AK_BIN: a seat opened by `ak orch` from a person's terminal on a fake muse that
keeps the line it was started with, its session reported by that line's SessionStart hook and
logged where Muse logs it, under a data home of the seat's own, and its PreLLMCall hook run as
Muse runs it -- `sh -c`, the call's JSON on stdin, none of the seat's environment, not even that
data home.  Fails on today's ak, whose launch carries no such hook.
"""

import json
import os
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import PANE
from fixtures.akterm import Terminal
from test_key_model_followed_opencode_muse import SPARK, muse_answer
from test_key_muse_hooks import settings

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SESSION = "01a18c52-a770-75a1-9576-acme00000002"
REMINDER = "01a18c52-a770-75a1-9576-acme00000003"     # a reminder's own session: no log
RUN = "01a18c52-0000-7000-8000-run000000002"
NAMED = "Spark 1.3 Contributor"     # what every screen names SPARK (config.model_label)

# muse: a schema naming the hooks this test runs, and a TUI, the one call made on a terminal,
# that keeps the line it was started with and shows Muse's composer.  Anything else (ak's usage
# probe) fails, as offline.
MUSE = """#!/bin/sh
if [ "$1 $2 $3" = "schema generate-json-schema --out" ]; then
  echo '{{"hook_event": {{"enum": ["notification", "preLLMCall"]}}}}' >"$4/muse.schema.json"
  exit 0
fi
[ -t 0 ] || exit 1
{python} -c 'import json, sys; json.dump(sys.argv[2:], open(sys.argv[1], "w"))' {root}/argv.json "$@"
exec {python} {pane} {screen} {root}/typed
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EffortFollowedMuseAtItsCall(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["spark"])     # SPARK at xhigh
        home.env["XDG_DATA_HOME"] = str(home.path / "data")
        quote = lambda path: shlex.quote(str(path))
        home.fake("muse", MUSE.format(root=quote(home.root), python=quote(sys.executable),
                                      pane=quote(PANE),
                                      screen=quote(FIXTURES / "muse-prompt-pane.txt")))
        argv = home.root / "argv.json"
        self.term = Terminal(home, "orch", "acme", "--model", "spark", "--workers", "spark",
                             size=(120, 40))
        self.record_file = home.path / ".agentkit/state/session-acme.json"
        self.term.wait(f"{NAMED} xhigh", bound=60)
        self.until(lambda: argv.exists() and argv.read_text().endswith("]")
                   and "launched" in self.record())
        self.hooks = settings(json.loads(argv.read_text()))
        self.fire("SessionStart", {"hook_event_name": "SessionStart", "session_id": SESSION})
        day = datetime.fromtimestamp(time.time(), timezone.utc).strftime("%Y/%m/%d")
        self.log = home.write(f"data/muse/sessions/{day}/{SESSION}/session.jsonl", "")

    def record(self):
        return json.loads(self.record_file.read_text())

    def until(self, test, bound=30):
        deadline = time.monotonic() + bound
        while not test():
            self.assertLess(time.monotonic(), deadline, self.term.screen())
            time.sleep(0.05)

    def fire(self, event, payload, env=None):
        """Run each command the launch gave Muse for the event, as Muse runs one: `sh -c`, the
        event's JSON on stdin, and none of the seat's environment; each prints nothing."""
        self.assertIn(event, set(self.hooks))
        for group in self.hooks[event]:
            for hook in group["hooks"]:
                done = self.home.run("sh", "-c", hook["command"], input=json.dumps(payload),
                                     env={"XDG_DATA_HOME": None, **(env or {})})
                self.assertEqual((done.code, done.out), (0, ""), done.err)

    def call(self, session, effort, env=None):
        """A model call of that session, at that effort, as Muse 1.4.15 hands it to the hook."""
        self.fire("PreLLMCall", env=env, payload={
            "session_id": session, "model": SPARK,
            "options": {"meta.max_output_tokens": 128000, "meta.reasoning.effort": effort},
            "messages": [{"role": "user", "content": "Rename the acme report."}],
            "tools": [{"name": "shell", "description": "Run a command."}]})

    def reports(self):
        return list((self.home.path / ".agentkit/state").glob(f"model-{SESSION}*"))

    def followed(self, effort):
        self.until(lambda: self.record().get("efforts", {}).get("spark", {}).get("effort")
                   == effort)
        self.assertEqual(self.record()["orchestrator"], "spark")
        self.term.wait(f"{NAMED} {effort}")

    def test_the_hook_runs_beside_each_call(self):
        self.assertTrue(all(hook.get("async") is True for group in self.hooks["PreLLMCall"]
                            for hook in group["hooks"]))

    def test_a_calls_effort_reaches_the_record_and_bar_with_no_new_answer(self):
        self.call(SESSION, "low")
        self.followed("low")

    def test_a_call_that_changes_nothing_runs_no_python_and_writes_its_report_anew(self):
        # the seat may have been moved on `c` and back inside Muse since the report was kept
        self.call(SESSION, "low")
        self.followed("low")
        for report in self.reports():
            os.utime(report, (1000, 1000))
        fakes, ran = self.home.root / "no-python", self.home.root / "python-ran"
        fakes.mkdir()
        (fakes / "python3").write_text(f"#!/bin/sh\ntouch {shlex.quote(str(ran))}\nexit 1\n")
        (fakes / "python3").chmod(0o755)
        self.call(SESSION, "low", env={"PATH": f"{fakes}:{self.home.env['PATH']}"})
        self.assertFalse(ran.exists())
        self.assertGreater(max(report.stat().st_mtime for report in self.reports()), 1000)

    def test_an_answer_on_that_model_after_the_call_leaves_its_effort_standing(self):
        # the call's own answer, dated after the call, in the log before any look of ak's
        self.log.write_text(muse_answer(SESSION, RUN, time.time() + 60, SPARK, "startup"))
        self.call(SESSION, "medium")
        self.followed("medium")

    def test_a_reminders_call_keeps_the_seats_effort_and_no_report(self):
        held = self.record().get("efforts")
        self.call(REMINDER, "minimal")
        done = self.home.ak("orch", "list")
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.record().get("efforts"), held)
        self.assertEqual(sorted((self.home.path / ".agentkit/state").glob("model-*.json")), [])


if __name__ == "__main__":
    unittest.main()
