"""An armed tick launches one ordinary run per repository and previous UTC day, through AK_BIN.

Black-box: the merged runs are rows of the Home's history.db, written with sqlite3 as ak keeps
them and dated by the real clock, so a test the UTC day turns under runs again.
"""

from contextlib import closing
import json
from pathlib import Path
import shlex
import shutil
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import AK, Home, boxable
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_history_db import DATABASE, ORIGINAL

DAY = 86400
MODELS = ["opus", "astra"]


class Held(list):
    """What a test reports, held until it is known to stand."""

    def __getattr__(self, name):
        return lambda *args: self.append((name, args))


def reaching(fakes):
    """The fakes, whose turns hand in to the program from a worker's box.  The box empties the
    temporary directories but for what it shows, so a turn that cannot see the program there,
    such as a wrapper beside a test's copy of a checkout, runs a copy of it."""
    for fake in fakes.values():
        ak, copy = fake.dir / "ak", shlex.quote(shutil.copy(AK, fake.dir / "ak-copy").as_posix())
        ak.write_text(f"#!/bin/sh\n[ -e {shlex.quote(AK)} ] || exec {copy} \"$@\"\n"
                      f"exec {shlex.quote(AK)} \"$@\"\n")
        ak.chmod(0o755)
        fake.script.write_text(fake.script.read_text().replace(shlex.quote(AK),
                                                               shlex.quote(str(ak))))
    return fakes


def state(directory):
    return json.loads((directory / "run.json").read_text())


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class NightReview(unittest.TestCase):
    def run(self, result=None):
        # A UTC day that turns under a test moves the yesterday it dated its history in: what
        # it reported is dropped, and it runs again in a new Home.
        day, held = time.time() // DAY, Held()
        super().run(held)
        if time.time() // DAY != day:
            return self.run(result)
        for name, args in held:
            getattr(result, name)(*args)
        return result

    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, MODELS)
        self.fakes = reaching(fakeadapter.install(home, claude="not-needed", codex="not-needed"))
        GitHub(home)
        self.rig = Rig(home, "api", files={"AGENTS.md": "---\ntests: true\n---\n# api\n"})
        self.first, self.last = self.rig.head(), self.rig.commit({"api.py": "value = 1\n"})
        self.yesterday = time.time() // DAY * DAY - DAY
        day = time.strftime("%Y-%m-%d", time.gmtime(self.yesterday))
        self.task = home.path / f".agentkit/tasks/api/night-review-{day}.md"
        for name, created in (("last-merge", 1), ("newest", 2)):
            home.write(f".agentkit/state/session-{name}.json", {
                "orchestrator": "opus", "workers": ["opus"], "reviewers": ["astra"],
                "repo": str(self.rig.path), "cwd": str(self.rig.path), "created": created})
        self.db = home.path / DATABASE
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TABLE runs (%s, changed_lines INTEGER, merge_sha TEXT, "
                       "broke_after_merge TEXT)" % ", ".join(map(" ".join, ORIGINAL)))

    def seed(self, count=100, breaks=(True, True), seat="last-merge"):
        """The history is `count` merged runs yesterday and as many a week before, the first of
        each day on its first commit and broken after merge where `breaks` says."""
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("DELETE FROM runs")
        self.merged((f"merged-{week}-{n}", "api", seat, self.yesterday - week * 7 * DAY + n,
                     self.last if n else self.first, "health" if n == 0 and breaks[week] else "")
                    for week in range(2) for n in range(count))

    def merged(self, rows):
        """Rows of merged runs, as ak keeps them: (run, repository, seat, finished at, merge sha,
        what broke after merge)."""
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executemany("INSERT INTO runs (run_id, repo, session, final_state, started_at, "
                           "finished_at, changed_lines, merge_sha, broke_after_merge) "
                           "VALUES (?, ?, ?, 'pass', ?, ?, 1, ?, ?)",
                           [(run, repo, seat, at - 1, at, sha, broke)
                            for run, repo, seat, at, sha, broke in rows])

    def stop(self, *seats):
        for name in seats:
            self.home.write(f".agentkit/state/seat-{name}.json", {"stopped_at": time.time()})

    def tick(self, failing=False):
        """One tick, whose night review says it failed only when `failing`; the runs after it."""
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        warned = [line.split(":")[0] for line in done.out.splitlines()
                  if ": no night review" in line]
        self.assertEqual(warned, ["WARN api"] if failing else [], done.out)
        return taskfile.runs(self.home)

    def doctor(self):
        done = self.home.ak("doctor")
        self.assertEqual(done.code, 0, done.out + done.err)
        line, = [line for line in done.out.splitlines() if line.startswith("night review  ")]
        return line

    def test_armed_launches_once_and_uses_the_last_merges_seat(self):
        self.seed()
        self.rig.git("config", "remote.origin.fetch", "+refs/heads/dev:refs/remotes/origin/dev")
        self.rig.git("update-ref", "refs/remotes/origin/main", self.first)
        self.rig.git("tag", "origin/main", self.first)
        self.rig.git("branch", "origin/main", self.first)
        directory, = self.tick()
        record = state(directory)
        self.assertEqual((record["task_file"], record["launched_session"], record["state"]),
                         (str(self.task), "last-merge", "not_needed"))
        body = self.task.read_text()
        self.assertRegex(body, f"{self.first}.*{self.last}")
        self.assertIn("```bash\ntrue\n```", body)
        self.assertEqual(self.tick(), [directory])
        self.assertTrue(self.doctor().startswith("night review  armed"))
        self.assertEqual(self.doctor().count("1.0%"), 2)

    def test_point_two_percent_disarms_and_starts_none(self):
        self.seed(500)
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.doctor(), "night review  disarmed · last two weeks 1/500 (0.2%) · 1/500 (0.2%)")

    def test_any_existing_run_claims_the_task_even_after_it_ends(self):
        self.seed()
        for kept in ("queued", "running", "pass", "error", "stopped", "not_needed"):
            directory = self.home.write(".agentkit/runs/ended/run.json", {
                "state": kept, "task_file": str(self.task), "reported": True}).parent
            self.assertEqual(self.tick(), [directory])
        self.assertEqual(sum(fake.n for fake in self.fakes.values()), 0)

    def test_both_weeks_must_exceed_half_a_percent(self):
        for count, breaks in ((200, (True, True)), (100, (True, False)), (100, (False, True))):
            self.seed(count, breaks)
            self.assertEqual(self.tick(), [])
            self.assertIn("disarmed", self.doctor())

    def test_a_launch_that_fails_stays_queued_for_the_next_tick(self):
        self.seed()
        # the owner's config holds a memory cap no run can be placed under: a cause outside ak
        akconfig.write(self.home, MODELS, settings={"run_memory_max_mb": 0})
        directory, = self.tick(failing=True)
        self.assertEqual(state(directory)["state"], "queued")
        akconfig.write(self.home, MODELS)
        self.assertEqual(self.tick(), [directory])
        self.assertEqual(state(directory)["state"], "not_needed")

    def test_each_repository_gets_its_own_run(self):
        self.seed()
        other = Rig(self.home, "web", files={"AGENTS.md": "---\ntests: true\n---\n"})
        self.home.write(".agentkit/state/session-web.json", {
            "orchestrator": "opus", "workers": ["opus"], "reviewers": ["astra"],
            "repo": str(other.path), "cwd": str(other.path)})
        self.merged([("web-merge", "web", "web", self.yesterday, other.head(), None)])
        directories = self.tick()
        self.assertEqual({state(d)["launched_session"] for d in directories}, {"last-merge", "web"})
        self.assertEqual(self.tick(), directories)

    def test_an_unavailable_origin_leaves_no_claim_and_the_next_tick_retries(self):
        self.seed()
        self.stop("last-merge")
        self.rig.git("remote", "set-url", "origin", str(self.home.root / "missing"))
        self.assertEqual(self.tick(failing=True), [])
        self.rig.git("remote", "set-url", "origin", str(self.rig.bare))
        directory, = self.tick()
        self.assertEqual(state(directory)["launched_session"], "newest")

    def test_a_stopped_fallback_seat_is_skipped(self):
        self.seed(seat="gone")
        self.stop("newest")
        directory, = self.tick()
        self.assertEqual(state(directory)["launched_session"], "last-merge")

    def test_a_project_with_no_seat_launches_nothing_and_doctor_says_so(self):
        self.seed()
        self.stop("last-merge", "newest")
        self.assertEqual(self.tick(), [])
        self.assertIn("api: no seat", self.doctor())


if __name__ == "__main__":
    unittest.main()
