"""An armed tick launches one ordinary run per repository and previous UTC day, through AK_BIN."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import AK, REPO, Home, boxable
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

DAY = 86400
NOW = 1_800_000_000 // DAY * DAY + 60
DATE = datetime.fromtimestamp(NOW - DAY, timezone.utc).date().isoformat()
CLOCK = """
import sys, time
from pathlib import Path
if sys.argv[:1] == [{ak!r}]:
    sys.path[:0] = [{repo!r}, {tests!r}]
    from fixtures.clock import Clock
    from agentkit import history, night_review, watch
    for module in (history, night_review, watch):
        module.time = Clock(time.sleep)
        module.time.time = lambda: {now}
    seed = Path({seed!r})
    if seed.with_name("refuse").exists():
        from unittest.mock import patch
        patch("agentkit.orch.start_in_slice", side_effect=OSError("temporary fork failure")).start()
    passes = ("dead loops", "stall recovery", "night review") if seed.with_name("recover").exists() else ("night review",)
    table = watch.local_passes
    watch.local_passes = lambda *args: [p for p in table(*args) if p[0] in passes]
    if seed.exists():
        exec(seed.read_text())
        seed.unlink()
"""


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class NightReview(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        self.fakes = fakeadapter.install(home, claude="not-needed", codex="not-needed")
        GitHub(home)
        self.rig = Rig(home, "api", files={"AGENTS.md": "---\ntests: true\n---\n# api\n"})
        self.first, self.last = self.rig.head(), self.rig.commit({"api.py": "value = 1\n"})
        self.task = home.path / f".agentkit/tasks/api/night-review-{DATE}.md"
        for name, created in (("last-merge", 1), ("newest", 2)):
            home.write(f".agentkit/state/session-{name}.json", {
                "orchestrator": "opus", "workers": ["opus"], "reviewers": ["astra"],
                "repo": str(self.rig.path), "cwd": str(self.rig.path), "created": created})
        clock = home.write("clock/sitecustomize.py", CLOCK.format(
            ak=AK, repo=str(Path(AK).resolve().parents[1]), tests=str(REPO / "tests"),
            now=NOW, seed=str(home.path / "clock/seed.py")))
        self.env = {"PYTHONPATH": str(clock.parent)}

    def seed(self, count=100, breaks=(True, True), seat="last-merge"):
        return self.home.write("clock/seed.py", f"""
for week in range(2):
    for n in range({count}):
        name = f"merged-{{week}}-{{n}}"
        at = {NOW} - (week * 7 + 1) * {DAY} + n
        history.start_run(name, repo="api", session={seat!r}, started_at=at - 1)
        history.finish_run(name, final_state="pass", finished_at=at, changed_lines=1)
        history.update_run(name, merge_sha={self.last!r} if n else {self.first!r},
                           broke_after_merge="health" if n == 0 and {breaks!r}[week] else "")
""")

    def tick(self):
        done = self.home.tick(env=self.env)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual([line for line in done.out.splitlines() if line.startswith("WARN ")], [])
        return taskfile.runs(self.home)

    def doctor(self):
        done = self.home.ak("doctor", env=self.env)
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
        state = json.loads((directory / "run.json").read_text())
        self.assertEqual((state["task_file"], state["launched_session"], state["state"]),
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
        for state in ("queued", "running", "pass", "error", "stopped", "not_needed"):
            directory = self.home.write(".agentkit/runs/ended/run.json", {
                "state": state, "task_file": str(self.task), "reported": True}).parent
            self.assertEqual(self.tick(), [directory])
        self.assertEqual(sum(fake.n for fake in self.fakes.values()), 0)

    def test_both_weeks_must_exceed_half_a_percent(self):
        for count, breaks in ((200, (True, True)), (100, (True, False)), (100, (False, True))):
            self.seed(count, breaks)
            self.assertEqual(self.tick(), [])
            self.assertIn("disarmed", self.doctor())

    def test_a_failed_process_launch_stays_queued_for_the_next_tick(self):
        self.seed()
        refuse = self.home.write("clock/refuse", "")
        done = self.home.tick(env=self.env)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("WARN api: no night review", done.out)
        directory, = taskfile.runs(self.home)
        self.assertEqual(json.loads((directory / "run.json").read_text())["state"], "queued")
        refuse.unlink()
        self.home.write("clock/recover", "")
        self.assertEqual(self.tick(), [directory])
        self.assertEqual(json.loads((directory / "run.json").read_text())["state"], "not_needed")

    def test_each_repository_gets_its_own_run(self):
        seed = self.seed()
        other = Rig(self.home, "web", files={"AGENTS.md": "---\ntests: true\n---\n"})
        self.home.write(".agentkit/state/session-web.json", {
            "orchestrator": "opus", "workers": ["opus"], "reviewers": ["astra"],
            "repo": str(other.path), "cwd": str(other.path)})
        seed.write_text(seed.read_text() + f"""
history.start_run("web-merge", repo="web", session="web", started_at={NOW - DAY})
history.finish_run("web-merge", final_state="pass", finished_at={NOW - DAY}, changed_lines=1)
history.update_run("web-merge", merge_sha={other.head()!r})
""")
        directories = self.tick()
        self.assertEqual({json.loads((d / "run.json").read_text())["launched_session"]
                          for d in directories}, {"last-merge", "web"})
        self.assertEqual(self.tick(), directories)

    def test_an_unavailable_origin_leaves_no_claim_and_the_next_tick_retries(self):
        self.seed()
        self.home.write(".agentkit/state/seat-last-merge.json", {"stopped_at": NOW})
        self.rig.git("remote", "set-url", "origin", str(self.home.root / "missing"))
        done = self.home.tick(env=self.env)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("WARN api: no night review", done.out)
        self.assertEqual(taskfile.runs(self.home), [])
        self.rig.git("remote", "set-url", "origin", str(self.rig.bare))
        directory, = self.tick()
        self.assertEqual(json.loads((directory / "run.json").read_text())["launched_session"], "newest")

    def test_a_stopped_fallback_seat_is_skipped(self):
        self.seed(seat="gone")
        self.home.write(".agentkit/state/seat-newest.json", {"stopped_at": NOW})
        directory, = self.tick()
        self.assertEqual(json.loads((directory / "run.json").read_text())["launched_session"], "last-merge")

    def test_a_project_with_no_seat_launches_nothing_and_doctor_says_so(self):
        self.seed()
        for path in (self.home.path / ".agentkit/state").glob("session-*.json"):
            name = path.stem.removeprefix("session-")
            self.home.write(f".agentkit/state/seat-{name}.json", {"stopped_at": NOW})
        self.assertEqual(self.tick(), [])
        self.assertIn("api: no seat", self.doctor())


if __name__ == "__main__":
    unittest.main()
