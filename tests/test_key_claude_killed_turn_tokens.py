"""A Claude worker turn that ends without its `result` keeps the tokens its transcript shows.

Such a turn's `turn_usage` rows in history.db hold, for each model, each type summed over the
messages its session's transcripts hold from its start to its last event, its subagent's too,
each message once however many lines repeat it.  Where no transcript came home, as from a turn
killed on a rented machine, each message counts as its stream reported it, and the run's
executor tokens count each message once too.  Those of a turn killed before its stream showed
a message count what its rows count.  A turn with its `result` keeps what the result gives.  A
later turn resuming the session keeps what its result's total exceeds the rows kept for the
session's turns: those of a killed turn whose transcript came home, and none of one whose
transcript did not, which the session never held.  Black-box: AK_BIN runs tasks through
tests/fixtures/akbin.py on a fake Claude harness.
While the executor's turn waits, the test does what Claude Code would: it writes the turn's
events, naming the session and the turn's working directory, and that session's transcripts in
the Home's Claude projects folder.  history.db is read with sqlite3.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

OWNERS = {"AK_NOTIFY_SINK": None}
SESSION = "session-acme"
OPUS, HAIKU = "claude-opus-5", "claude-haiku-5"
TYPES = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
         "output_tokens")
MODEL_TYPES = ("inputTokens", "cacheCreationInputTokens", "cacheReadInputTokens", "outputTokens")

# (message id, model, counts of each line repeating it, when): `before` the turn began, `during`
# it, `after` its last event.  A message's first line counts only its first chunk of output.
MAIN = [("msg_earlier", OPUS, [(1000, 1000, 1000, 1000)], "before"),
        ("msg_1", OPUS, [(6, 2000, 10000, 3), (6, 2000, 10000, 1575)], "during"),
        ("msg_2", OPUS, [(4, 300, 12000, 1), (4, 300, 12000, 80000)], "during"),
        ("msg_later", OPUS, [(500, 500, 500, 500)], "after")]
SUBAGENT = [("msg_sub", HAIKU, [(5, 700, 0, 90), (5, 700, 0, 90)], "during")]
# What the fix resuming the session spent itself; a finding it answers, so its review passes.
GREW = {OPUS: (7, 70, 700, 17), HAIKU: (1, 10, 0, 3)}
FINDING = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "fixture defect", "the fixture says so", "--run",
     'test "$(cat retry.txt)" != hello'], ["done"]]}
FIX = {"write": {"retry.txt": "hello again\n"}, "commit": "fix retry.txt",
       "final": "## Summary\nfixed", "hand_in": [["done"]], "session": SESSION}


def stamp(moment):
    """A moment as Claude Code's transcripts write it."""
    return datetime.fromtimestamp(moment, timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def transcript(path, messages, times, sidechain=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "user", "uuid": "u-0", "timestamp": stamp(times["during"]),
              "sessionId": SESSION, "isSidechain": sidechain,
              "message": {"role": "user", "content": "Add the retry file."}}]
    for message, model, repeats, when in messages:
        lines += [{"type": "assistant", "uuid": f"{message}-{n}", "timestamp": stamp(times[when]),
                   "sessionId": SESSION, "isSidechain": sidechain,
                   "message": {"id": message, "role": "assistant", "model": model,
                               "content": [{"type": "text", "text": "Working."}],
                               "usage": dict(zip(TYPES, counts))}}
                  for n, counts in enumerate(repeats)]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))


def events(workspace, result, shown):
    """The turn's stream: its start, each message's first chunk once per content block, as Claude
    Code repeats a message's id and usage, unless it was killed before it showed one, and the
    `result` if it has one."""
    lines = [{"type": "system", "subtype": "init", "cwd": workspace, "session_id": SESSION,
              "model": OPUS}]
    lines += [{"type": "assistant", "session_id": SESSION, "message": {
        "id": message, "model": model, "usage": dict(zip(TYPES, repeats[0]))}}
        for message, model, repeats, when in MAIN + SUBAGENT if when == "during" and shown
        for _block in ("thinking", "text")]
    if result is not None:
        lines.append({"type": "result", "subtype": "success", "session_id": SESSION,
                      "usage": dict(zip(TYPES, result)),
                      "modelUsage": {OPUS: dict(zip(MODEL_TYPES, result))}})
    return "".join(json.dumps(line) + "\n" for line in lines)


def resumed(models):
    """The fix's stream: its start and its result, whose `modelUsage` totals the session."""
    return "".join(json.dumps(line) + "\n" for line in (
        {"type": "system", "subtype": "init", "session_id": SESSION},
        {"type": "result", "subtype": "success", "session_id": SESSION,
         "usage": dict(zip(TYPES, GREW[OPUS])),
         "modelUsage": {model: dict(zip(MODEL_TYPES, counts)) for model, counts in models.items()}}))


class Turn:
    """One run whose Claude executor waits while the test writes what Claude Code would, and
    where `fix` streams, a round 2 fix resuming the session."""

    @classmethod
    def start(cls, result=None, transcripts=True, fix=None, shown=True):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        fake = fakeadapter.install(cls.home, claude="work",
                                   codex=[FINDING, "pass"] if fix else "pass")["claude"]
        held, part, release = (fake.dir / name for name in ("held", "held.part", "release"))
        cls.addClassCleanup(release.touch)
        # it names the working directory as Claude Code's process sees it, then waits
        part_, held_, release_ = (shlex.quote(str(path)) for path in (part, held, release))
        fake.behave({**fakeadapter.WORK, "session": SESSION,
                     "sh": f"pwd -P > {part_} && mv {part_} {held_}; "
                     f"while [ ! -f {release_} ]; do sleep 0.1; done"},
                    *([{**FIX, "events": fix}] if fix else []))
        proc = cls.home.spawn("run", str(taskfile.write(cls.home, rig.path)), "--no-merge",
                              env=OWNERS)
        deadline = time.monotonic() + 120
        while not held.exists():
            if proc.poll() is not None or time.monotonic() > deadline:
                raise AssertionError("the executor's turn never began: "
                                     + cls.home.log("spawn-1.err").read_text())
            time.sleep(0.1)
        workspace = held.read_text().strip()
        cls.run_dir = taskfile.only_run(cls.home)
        cls.out = max(cls.run_dir.glob("round-*/*/harness"),
                      key=lambda receipt: receipt.stat().st_mtime).parent
        (cls.out / "events.jsonl").write_text(events(workspace, result, shown))
        began = (cls.out / "harness").stat().st_mtime
        ended = (cls.out / "events.jsonl").stat().st_mtime
        times = {"before": began - 60, "during": (began + ended) / 2, "after": ended + 60}
        # Claude Code's folder for a short path: every character not a letter or digit a hyphen
        project = cls.home.path / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", workspace)
        if transcripts:
            transcript(project / f"{SESSION}.jsonl", MAIN, times)
            transcript(project / SESSION / "subagents/agent-a1.jsonl", SUBAGENT, times, True)
        release.touch()
        cls.code = proc.wait(timeout=300)
        connection = sqlite3.connect(cls.home.path / ".agentkit/history.db")
        try:
            cls.rows = connection.execute(
                "SELECT turn, role, model, input, cache_write, cache_read, output "
                "FROM turn_usage ORDER BY model").fetchall()
            cls.executor_tokens = connection.execute(
                "SELECT executor_tokens FROM runs").fetchone()[0]
        finally:
            connection.close()

    def test_the_run_passes(self):
        self.assertEqual(self.code, 0, self.home.log("spawn-1.err").read_text())
        self.assertEqual(json.loads((self.run_dir / "run.json").read_text())["state"], "pass")

    def kept(self, fix=False):
        """The killed turn's rows, or the fix's."""
        turn = str(self.out.resolve())
        return [(model, *counts) for kept, role, model, *counts in self.rows
                if role == "executor" and (kept == turn) != fix]


class AKilledTurn(Turn, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # the session holds the killed turn's messages, so the fix's total counts them too
        cls.start(fix=resumed({OPUS: (17, 2370, 22700, 81592), HAIKU: (6, 710, 0, 93)}))

    def test_each_model_keeps_its_messages_from_the_turn_s_start_to_its_last_event_once(self):
        # msg_1 and msg_2 at their final counts, the subagent's message once; neither the
        # resumed session's earlier message nor the one after the last event
        self.assertEqual(self.kept(), [(HAIKU, 5, 700, 0, 90), (OPUS, 10, 2300, 22000, 81575)])
        self.assertEqual(len(self.rows), 4, self.rows)

    def test_the_fix_resuming_its_session_keeps_only_what_it_spent_itself(self):
        self.assertEqual(self.kept(fix=True), [(model, *GREW[model]) for model in (HAIKU, OPUS)])


class AKilledTurnWhoseTranscriptNeverCameHome(Turn, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # the session never held the killed turn's messages: the fix's total is its own
        cls.start(transcripts=False, fix=resumed(GREW))

    def test_each_message_counts_as_its_stream_reported_it(self):
        # input and cache whole, output its first chunk's
        self.assertEqual(self.kept(), [(HAIKU, 5, 700, 0, 90), (OPUS, 10, 2300, 22000, 4)])
        self.assertEqual(len(self.rows), 4, self.rows)

    def test_the_fix_resuming_its_session_keeps_its_whole_total(self):
        self.assertEqual(self.kept(fix=True), [(model, *GREW[model]) for model in (HAIKU, OPUS)])

    def test_the_run_s_executor_tokens_count_each_message_once(self):
        # beside the fix's, which its result's own `usage` gives
        self.assertEqual(self.executor_tokens, sum(sum(counts) for _, *counts in self.kept())
                         + sum(GREW[OPUS]))


class AKilledTurnWhoseStreamShowedNoMessage(Turn, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start(shown=False)

    def test_each_model_keeps_its_messages_its_transcripts_hold(self):
        self.assertEqual(self.kept(), [(HAIKU, 5, 700, 0, 90), (OPUS, 10, 2300, 22000, 81575)])
        self.assertEqual(len(self.rows), 2, self.rows)

    def test_the_run_s_executor_tokens_are_what_they_count(self):
        self.assertEqual(self.executor_tokens, sum(sum(counts) for _, *counts in self.kept()))


class ATurnWithItsResult(Turn, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start(result=(7, 70, 700, 17))

    def test_it_keeps_what_its_result_gives_whatever_its_transcript_holds(self):
        self.assertEqual(self.kept(), [(OPUS, 7, 70, 700, 17)])
        self.assertEqual(len(self.rows), 1, self.rows)


if __name__ == "__main__":
    unittest.main()
