"""A job launched from a seat saves none of the owner's words; `ak run gc` takes saved ones out.

The owner's words are what a job is measured against: the orchestrator holds them whole and ak
keeps no copy, since a copy handed on breeds false findings and carries any key the owner pasted
(AGENTS.md's owner rules).  Job receipts once saved what the owner had typed into the seat since
its last job, and one held such a key.  So a job of two tasks launched from a seat whose
conversation holds a key writes it nowhere under ~/.agentkit and tells it to no turn; and a
collection pass takes the saved words, and the cursor that followed them, out of an older
install's receipt and seat record, says which receipt, and leaves the rest of each as it was.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its
turns on a harness the test adds as an adapter: tests/fixtures/adapters/echo.toml, beside a
script that keeps each prompt and hands in at once.  ak runs with a /tmp of its own, because
collection sweeps /tmp and the machine's is not the test's to sweep.
"""

from datetime import datetime, timezone
import json
import shlex
import shutil
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, REAL_TMUX, REPO, Home
from fixtures.akseat import Seat

KEY = "sk-acme-0000000000000000000000"
SAID = f"Build the API. Use {KEY} for the sandbox."
CURSOR = {"at": 30, "count": 1}
TASK = "---\nrepo: none\n---\n# {}\n\n## Done when\n```bash\ntrue\n```\n"
MODEL = ('\n[models.echo]\nharness = "echo"\nmodel = "echo-1"\neffort = "low"\n'
         'provider = "test"\n\n[providers.test]\nmode = "subscription"\n')
# A turn keeps its prompt and hands in at once: an executor's work done, a reviewer's pass.
# Every turn's shell is pid 2 in its box, so the copies are named by mktemp.
TURN = """#!/bin/sh
case "$1" in
  run) mkdir -p -- "$6"; cp -- "$5" "$(mktemp {dir}/prompt-XXXXXX)"
       (cd -- "$4" && {ak} hand-in done) >"$6/stderr.log" 2>&1
       printf '## Summary\\nnothing to change\\n' >"$6/final.md"; : >"$6/session_id" ;;
  auth) echo "the fixture needs no login" ;;
  *) echo "the fixture never speaks $1" >&2; exit 2 ;;
esac
"""


def sealed(home, *args, **kwargs):
    """ak with a /tmp and /var/tmp of its own, this Home's directories bound back in."""
    return home.run("bwrap", "--dev-bind", "/", "/", "--tmpfs", "/tmp", "--tmpfs", "/var/tmp",
                    "--bind", str(home.root), str(home.root),
                    "--bind", str(home.tmux_dir), str(home.tmux_dir), "--", AK, *args, **kwargs)


def holding(home):
    """Each file under ~/.agentkit that holds the key."""
    return [str(path.relative_to(home.path)) for path in (home.path / ".agentkit").rglob("*")
            if path.is_file() and KEY.encode() in path.read_bytes()]


@unittest.skipUnless(shutil.which("bwrap") and REAL_TMUX, "needs bwrap and tmux")
class Launch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.adapters = home.root / "adapters"
        cls.adapters.mkdir()
        # [worker] state is the one place beside its workspace that a turn's box shows it
        manifest = (REPO / "tests/fixtures/adapters/echo.toml").read_text()
        (cls.adapters / "echo.toml").write_text(manifest.replace(
            "[worker]\nstate = []", f"[worker]\nstate = {json.dumps([str(cls.adapters)])}"))
        script = cls.adapters / "echo.sh"
        script.write_text(TURN.replace("{dir}", shlex.quote(str(cls.adapters)))
                          .replace("{ak}", shlex.quote(AK)))
        script.chmod(0o755)
        config = home.path / ".agentkit/config.toml"
        config.write_text(config.read_text() + MODEL)
        seat = Seat(home, "lagoon", record={"workers": ["echo"]})
        # what the owner typed into the seat a minute ago, where Claude Code keeps it
        project = "".join(c if c.isascii() and c.isalnum() else "-" for c in str(seat.cwd))
        at = datetime.fromtimestamp(time.time() - 60, timezone.utc).isoformat()
        home.write(f".claude/projects/{project}/{seat.record['conversation']}.jsonl",
                   json.dumps({"type": "user", "timestamp": at,
                               "message": {"role": "user", "content": SAID}}) + "\n")
        tasks = []
        for title in ("Fix API", "Fix UI"):
            tasks.append(seat.cwd / f"{title.lower().replace(' ', '-')}.md")
            tasks[-1].write_text(TASK.format(title))
        cls.done = sealed(home, "run", *map(str, tasks), cwd=seat.cwd, timeout=300, env={
            "AGENTKIT_SESSION": "lagoon", "AGENTKIT_ADAPTER_DIR": str(cls.adapters)})
        cls.receipts = sorted((home.path / ".agentkit/jobs").glob("*/job.json"))

    def test_the_seat_runs_a_job_of_both_tasks(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(len(self.receipts), 1)
        job = json.loads(self.receipts[0].read_text())
        self.assertEqual(job["seat"], "lagoon")
        self.assertEqual([task["name"] for task in job["tasks"]], ["fix-api.md", "fix-ui.md"])

    def test_nothing_ak_keeps_holds_the_owners_words(self):
        self.assertEqual(holding(self.home), [])

    def test_neither_the_receipt_nor_the_seat_record_has_words_or_a_cursor(self):
        job = json.loads(self.receipts[0].read_text())
        self.assertFalse({"owner_words", "owner_words_cursor"} & job.keys())
        record = self.home.path / ".agentkit/state/session-lagoon.json"
        self.assertNotIn("owner_words_cursor", json.loads(record.read_text()))

    def test_no_turn_is_told_the_owners_words(self):
        prompts = list(self.adapters.glob("prompt-*"))
        self.assertGreaterEqual(len(prompts), 2)     # each task's executor at least
        for prompt in prompts:
            self.assertNotIn(KEY, prompt.read_text())


@unittest.skipUnless(shutil.which("bwrap"), "needs bwrap")
class Collection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        Seat(home, "lagoon", alive=False, record={"owner_words_cursor": CURSOR})
        cls.record = home.path / ".agentkit/state/session-lagoon.json"
        cls.seat = json.loads(cls.record.read_text())
        # finished an hour ago: too recent for collection to take the receipts whole
        receipt = {"seat": "lagoon", "started_at": time.time() - 7200,
                   "finished_at": time.time() - 3600,
                   "tasks": [{"name": "fix-api.md", "state": "passed"}]}
        cls.kept = {"job_id": "20261012-acme-held", **receipt}
        cls.held = home.write(".agentkit/jobs/20261012-acme-held/job.json", {
            **cls.kept, "owner_words": [{"at": 20, "text": SAID}], "owner_words_cursor": CURSOR})
        cls.clean = home.write(".agentkit/jobs/20261013-acme-clean/job.json",
                               {"job_id": "20261013-acme-clean", **receipt})
        cls.untouched = cls.clean.read_bytes()
        cls.done = sealed(home, "run", "gc")

    def test_the_pass_names_the_receipt_it_took_words_out_of(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        said = [line for line in self.done.out.splitlines() if "owner's saved words" in line]
        self.assertEqual(said, ["gc: removed the owner's saved words from job 20261012-acme-held"])

    def test_that_receipt_keeps_everything_but_the_words_and_cursor(self):
        self.assertEqual(json.loads(self.held.read_text()), self.kept)

    def test_a_receipt_without_words_is_left_as_it_was(self):
        self.assertEqual(self.clean.read_bytes(), self.untouched)

    def test_the_seat_record_loses_only_its_cursor(self):
        expected = {key: value for key, value in self.seat.items()
                    if key != "owner_words_cursor"}
        self.assertEqual(json.loads(self.record.read_text()), expected)

    def test_nothing_ak_keeps_holds_the_owners_words_after_it(self):
        self.assertEqual(holding(self.home), [])

    def test_a_pass_with_nothing_saved_says_nothing_of_words(self):
        again = sealed(self.home, "run", "gc")
        self.assertEqual(again.code, 0, again.out + again.err)
        self.assertNotIn("owner's saved words", again.out)


if __name__ == "__main__":
    unittest.main()
