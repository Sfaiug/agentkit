"""A turn sent to a Linux machine whose image has no name for the machine's user, or no `id` to
ask, runs here: its container ends at once as a machine with no room does (252, helper.FULL), the
adapter never starts there, and the turn's record names this host. One whose user has a name runs
there.

Black-box: AK_BIN runs a task through tests/fixtures/akbin.py on tests/fixtures/akmachine.py,
whose containers have `container=docker` in their environment and run the machine's programs,
here a fake `id` that answers in a container as such an image would; history.db is read with
sqlite3, and the fake adapters count their turns wherever they run.
"""

from contextlib import closing
import json
from pathlib import Path
import socket
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

WHERE = 'echo "${container:-here}" >"${AK_HAND_IN%/*}/where"'
CLAUDE_EVENTS = "".join(json.dumps(event) + "\n" for event in (
    {"type": "system", "subtype": "init", "session_id": "session-acme"},
    {"type": "result", "subtype": "success", "session_id": "session-acme",
     "usage": {"input_tokens": 10, "output_tokens": 20},
     "modelUsage": {"claude-opus-5": {"inputTokens": 10, "outputTokens": 20}}}))
CODEX_EVENTS = "".join(json.dumps(event) + "\n" for event in (
    {"type": "thread.started", "thread_id": "thread-acme"},
    {"type": "turn.completed", "usage": {"input_tokens": 30, "output_tokens": 15}}))

# `id` in a container: of an image with no account for the user, and of one with no `id` at all;
# the machine's own, outside any container, answers as this host's.
NO_NAME = ('[ -z "$container" ] || [ "$*" != -un ] || '
           '{ echo "id: cannot find name for user ID 1001" >&2; exit 1; }')
NO_ID = '[ -z "$container" ] || { echo "id: command not found" >&2; exit 127; }'


class ATurnWhoseUserHasNoAccountRunsAtHome(unittest.TestCase):
    def run_task(self, image_id=None):
        """Where each turn ran, by `where` and by its record, the turn containers the machine
        started and each adapter's turns, with `image_id` the fake `id`'s first line."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\nhealth: none\ntests: true\n---\n# widgets\n",
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        akconfig.write(home, ["opus", "astra"],
                       extra='[machines.acme-linux]\nwork = ["turns"]\n')
        fakes = fakeadapter.install(
            home, claude={**fakeadapter.WORK, "sh": WHERE, "events": CLAUDE_EVENTS},
            codex={**fakeadapter.PASS, "sh": WHERE, "events": CODEX_EVENTS})
        machine = akmachine.install(home)
        for harness, version in (("claude", "1.2.3"), ("codex", "4.5.6")):
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
            place = machine / "home/.agentkit-helper/harness" / harness / version
            place.mkdir(parents=True)
            (place / harness).touch(0o755)
        if image_id:
            (machine / "bin/id").write_text(f'#!/bin/sh\n{image_id}\nexec /usr/bin/id "$@"\n')
            (machine / "bin/id").chmod(0o755)
        done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge",
                       env={"AK_NOTIFY_SINK": None, "AK_HOST_READINGS": akmachine.CROWDED},
                       timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run = taskfile.only_run(home)
        with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db:
            recorded = db.execute("SELECT role, machine FROM turn_usage WHERE run_id=? "
                                  "ORDER BY began, role", (run.name,)).fetchall()
        return (sorted(path.read_text().strip() for path in run.rglob("where")), recorded,
                len([*machine.glob("docker/roots/*-turn")]),
                (fakes["claude"].n, fakes["codex"].n))

    def test_a_user_the_image_has_no_name_for_runs_its_turns_here(self):
        here = socket.gethostname()
        for image_id in (NO_NAME, NO_ID):
            with self.subTest(image_id=image_id):
                self.assertEqual(self.run_task(image_id), (
                    ["here"] * 2, [("executor", here), ("reviewer", here)], 2, (1, 1)))

    def test_a_user_with_a_name_runs_its_turns_there(self):
        self.assertEqual(self.run_task(), (
            ["docker"] * 2, [("executor", "acme-linux"), ("reviewer", "acme-linux")], 2, (1, 1)))


if __name__ == "__main__":
    unittest.main()
