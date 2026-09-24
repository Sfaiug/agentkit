"""A review fails a round only for what blocks; three rounds is the budget.

Entirely offline fixture state: one fake harness per model in the catalogue answers
reviews from a plan the test writes, and the PR is opened through a stubbed `gh`.
"""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, run, worker


def fail(count, note="pattern"):
    """A reviewer answer with `count` blocking findings under `## Findings`."""
    items = "\n".join(f"- file.py:{n} - {note} - why it matters" for n in range(1, count + 1))
    return f"VERDICT: FAIL\n\n## Findings\n{items}\n" if count else "VERDICT: FAIL\n"


PASS = "VERDICT: PASS\n\n## Findings\n- none\n"

PASS_FOLLOWUPS = """VERDICT: PASS

## Findings
- none

## Follow-ups
- a.py:1 - rename this - clarity for readers
- b.py:2 - add a test - coverage for the new path
"""

# One fake harness for every model in the catalogue: it never leaves the fixture directory,
# records each prompt it was given, and answers reviews from a plan the test writes.
ADAPTER = '''import json, os, pathlib, sys
root = pathlib.Path(os.environ["GATE_FIXTURE"])
if sys.argv[1] == "usage":
    print(json.dumps({"meters": [{"name": "weekly", "used": 0}]}))
    sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available":0}')
    sys.exit(0)
assert sys.argv[1] == "run", sys.argv
out = pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
role = "reviewer" if prompt.startswith("You are the reviewer") else "executor"
with (root / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"role": role, "prompt": prompt, "session": sys.argv[7:]}) + "\\n")
deliverable = pathlib.Path(sys.argv[4], "deliverable")
if role == "executor":
    deliverable.write_text("fixture work\\n")
    (out / "final.md").write_text("## Summary\\nFixture work.")
else:
    plan = json.loads((root / "reviews.json").read_text())
    answer = plan.pop(0) if len(plan) > 1 else plan[0]
    (root / "reviews.json").write_text(json.dumps(plan))
    (out / "final.md").write_text(answer)
    (out / "session_id").write_text("session-" + role)
(out / "session_id").write_text("session-" + role)
'''


class ReviewGate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".review-gate-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "PATH": f"{self.bin}:{os.environ['PATH']}",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(sockets), "TMUX": "", "NO_COLOR": "1",
            "PYTHONDONTWRITEBYTECODE": "1", config.ADAPTER_DIR_ENV: str(adapters),
            "GATE_FIXTURE": str(self.root)}))
        # Nothing outside the fixture is reachable: no tmux server, harness, GitHub or Discord.
        self.script(self.bin / "tmux", '''import sys
assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv
sys.exit(1)
''')
        for executable in ("gh", "claude", "codex", "muse"):
            self.script(self.bin / executable, 'raise AssertionError("external call forbidden")\n')
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub call")))
        self.stack.enter_context(patch.object(notify, "post", side_effect=AssertionError("Discord")))
        self.stack.enter_context(patch.object(notify, "shaped", return_value=0))
        config.ensure_dirs()
        self.cfg = config.load()
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            self.script(adapters / f"{harness}.sh", ADAPTER)
        workers = self.cfg["defaults"]["workers"]
        self.executor = workers[0]
        self.reviewer = next(name for name in workers if config.model(self.cfg, name)["provider"] !=
                             config.model(self.cfg, self.executor)["provider"])
        self.task = self.root / "task.md"
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def reviews(self, *answers):
        (self.root / "reviews.json").write_text(json.dumps(list(answers)))

    def launch(self, rounds=None, *flags):
        """One scratch run, so the loop is the only thing under test: no repo, branch or PR."""
        front = f"---\nrepo: none\n{'' if rounds is None else f'rounds: {rounds}'}\n---\n"
        self.task.write_text(f"{front}# Budget fixture\n\n"
                             "## Done when\n```bash\ntest -f deliverable\n```\n")
        before = set(run.run_dirs())
        code = run.main([str(self.task), "--exec", self.executor, "--review", self.reviewer, *flags])
        directory = (set(run.run_dirs()) - before).pop()
        return code, directory, run.read_state(directory)

    def test_preamble_names_the_four_blocking_classes_and_the_follow_ups_heading(self):
        for role in ("reviewer", "reviewer-pr", "reviewer-scratch"):
            with self.subTest(role=role):
                text = worker.PREAMBLES[role].format(workspace=self.root)
                for words in ("a correctness defect in the task's outcome",
                              "a safety or data-loss risk",
                              "a check the executor weakened or skipped",
                              "a scope violation (work the task did not ask for, "
                              "or asked-for work missing)",
                              "## Follow-ups", "`path:line - what - why it matters`",
                              "never a reason to fail",
                              "however long the follow-ups list is",
                              "for blocking findings only"):
                    self.assertIn(words, text)
        for role in ("executor", "fixer"):
            with self.subTest(role=role):
                text = worker.PREAMBLES[role].format(workspace=self.root)
                self.assertIn("`## Blocked` is only for a task that cannot be completed as written; "
                              "never for a transient provider failure, a capacity refusal, or a check "
                              "the loop runs later such as the `# once` suite.", text)

    def test_pass_follow_ups_are_recorded_by_the_loop(self):
        self.reviews(PASS_FOLLOWUPS)
        code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 0, (directory / "log.txt").read_text())
        self.assertEqual(state["followups"],
                         ["a.py:1 - rename this - clarity for readers",
                          "b.py:2 - add a test - coverage for the new path"])

    def test_pass_follow_ups_land_in_pr_body_and_the_followups_file(self):
        repo = self.root / "repo"
        repo.mkdir()
        wt = self.root / "checkout"
        wt.mkdir()
        run_dir = config.RUNS / "20260922-0000-gate"
        run_dir.mkdir(parents=True)
        state = {"run_id": run_dir.name, "title": "gate fixture", "verdict": "PASS",
                 "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                      "summary": "did the work"}],
                 "rounds": 3, "base": "origin/main", "base_sha": "abc", "branch": "ak/gate",
                 "worktree": str(wt), "repo": str(repo), "executor": "opus", "reviewer": "astra",
                 "findings": "",
                 "followups": ["a.py:1 - rename this - clarity for readers",
                               "b.py:2 - add a test - coverage for the new path"],
                 "pr": None, "merge_method": "squash"}
        lp = run.Loop(self.cfg, run_dir, state, {}, lambda s: None, wt, "body", ["true"],
                      "context", [])
        url = "https://github.com/fixture/repo/pull/7"
        with patch.object(run, "gh", return_value=(0, f"opened {url}")):
            self.assertEqual(run.open_pr(lp, "main"), url)
        body = (run_dir / "pr-body.md").read_text()
        self.assertIn("## Follow-ups", body)
        self.assertIn("- a.py:1 - rename this - clarity for readers", body)
        self.assertIn("- b.py:2 - add a test - coverage for the new path", body)
        day = time.strftime("%Y-%m-%d", time.localtime())
        logged = (config.HOME / "followups" / "repo.md").read_text().splitlines()
        self.assertEqual(logged, [
            f"- {day} run {run_dir.name} PR #7: a.py:1 - rename this - clarity for readers",
            f"- {day} run {run_dir.name} PR #7: b.py:2 - add a test - coverage for the new path"])
        # writing them again changes nothing: each item is already there
        run.append_followups(state, url)
        self.assertEqual((config.HOME / "followups" / "repo.md").read_text().splitlines(), logged)

    def test_second_round_does_not_duplicate_a_follow_up(self):
        first = ("VERDICT: FAIL\n\n## Findings\n- a.py:1 - wrong answer - correctness\n\n"
                 "## Follow-ups\n- b.py:2 - rename that - clarity\n")
        second = ("VERDICT: PASS\n\n## Findings\n- none\n\n"
                  "## Follow-ups\n- b.py:2 - rename that - a different why\n"
                  "- c.py:3 - add a test - coverage\n")
        self.reviews(first, second)
        code, directory, state = self.launch(rounds=3)
        self.assertEqual(code, 0, (directory / "log.txt").read_text())
        self.assertEqual(state["followups"],
                         ["b.py:2 - rename that - clarity", "c.py:3 - add a test - coverage"])

    def test_default_budget_is_three_rounds_with_no_extension(self):
        self.reviews(fail(2), fail(2), fail(2))
        code, directory, state = self.launch()      # the task names no rounds of its own
        self.assertEqual(code, 1, (directory / "log.txt").read_text())
        self.assertEqual((state["state"], state["rounds"]), ("fail", 3))
        self.assertEqual(len(state["round_summaries"]), 3)
        self.assertNotIn("extended", state)
        self.assertNotIn("converging", (directory / "log.txt").read_text())
        self.assertFalse(hasattr(run, "extend"))
        self.assertFalse(hasattr(run, "EXTENSIONS"))

    def test_third_fail_hands_back_with_the_blocking_findings(self):
        blocking = ("VERDICT: FAIL\n\n## Findings\n"
                    "- a.py:1 - off-by-one in the gate - wrong outcome for edge input\n"
                    "- b.py:2 - drops the error - silent data loss\n\n"
                    "## Follow-ups\n- c.py:3 - rename this - clarity\n")
        self.reviews(fail(1), fail(1), blocking)
        code, directory, state = self.launch()
        self.assertEqual((code, state["state"]), (1, "fail"))
        self.assertEqual(run.handback_reason(state), "after 3 rounds, open findings: "
                         "- a.py:1 - off-by-one in the gate - wrong outcome for edge input "
                         "- b.py:2 - drops the error - silent data loss")
        line = run.handback_line(state, directory)
        self.assertIn("finished FAIL: after 3 rounds, open findings: - a.py:1 - off-by-one", line)
        self.assertIn("Decide the next step.", line)
        result = (directory / "result.md").read_text()
        self.assertIn("## Reviewer findings", result)
        self.assertIn("off-by-one in the gate", result)
        self.assertIn("drops the error", result)

    def test_rounds_five_is_refused_before_any_round(self):
        self.reviews(PASS)
        with self.assertRaisesRegex(config.Error, r"^--rounds 5 is over the budget: 3 rounds, then "
                                    r"a run goes back to its orchestrator to split or re-scope$"):
            self.launch(None, "--rounds", "5")
        self.assertEqual(run.run_dirs(), [])
        self.assertFalse((self.root / "calls.jsonl").exists())

    def test_task_template_defaults_to_three_rounds(self):
        path = REPO / "templates" / "task.md"
        meta, _, _ = run.parse_task(path)
        self.assertEqual(int(meta.get("rounds") or 3), 3)
        self.assertIn("`rounds` defaults to 3", path.read_text())

    def test_existing_pr_refreshes_pr_body_and_appends_only_new_follow_ups(self):
        repo = self.root / "repo"
        repo.mkdir()
        wt = self.root / "checkout"
        wt.mkdir()
        run_dir = config.RUNS / "20260922-0000-refresh"
        run_dir.mkdir(parents=True)
        state = {"run_id": run_dir.name, "title": "refresh fixture", "verdict": "PASS",
                 "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                      "summary": "did the work"}],
                 "rounds": 3, "base": "origin/main", "base_sha": "abc", "branch": "ak/refresh",
                 "worktree": str(wt), "repo": str(repo), "executor": "opus", "reviewer": "astra",
                 "findings": "", "followups": ["a.py:1 - rename this - clarity"],
                 "pr": None, "merge_method": "squash"}
        lp = run.Loop(self.cfg, run_dir, state, {}, lambda s: None, wt, "body", ["true"],
                      "context", [])
        url = "https://github.com/fixture/repo/pull/7"
        with patch.object(run, "gh", return_value=(0, f"opened {url}")):
            self.assertEqual(run.open_pr(lp, "main"), url)
            # a re-review after the PR already existed collects one more follow-up
            state["followups"].append("b.py:2 - add a test - coverage")
            self.assertEqual(run.open_pr(lp, "main"), url)
        body = (run_dir / "pr-body.md").read_text()
        self.assertIn("- b.py:2 - add a test - coverage", body)
        logged = (config.HOME / "followups" / "repo.md").read_text().splitlines()
        self.assertEqual(len(logged), 2)
        self.assertTrue(logged[0].endswith("a.py:1 - rename this - clarity"))
        self.assertTrue(logged[1].endswith("b.py:2 - add a test - coverage"))

    def test_concurrent_appends_keep_each_follow_up_once(self):
        repo = self.root / "repo"
        repo.mkdir()
        state = {"run_id": "20260922-0000-race", "repo": str(repo),
                 "followups": ["a.py:1 - rename this - clarity",
                               "b.py:2 - add a test - coverage"]}
        url = "https://github.com/fixture/repo/pull/7"
        threads = [threading.Thread(target=run.append_followups, args=(dict(state), url))
                   for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        logged = (config.HOME / "followups" / "repo.md").read_text().splitlines()
        self.assertEqual(len(logged), 2)
        self.assertEqual(sorted(line.rsplit(": ", 1)[1] for line in logged),
                         sorted(state["followups"]))

    def append(self, run_id, *items):
        """This repo's follow-ups file after one PR #7 appended `items`, and its new line prefix."""
        run.append_followups({"run_id": run_id, "repo": str(self.root / "repo"),
                              "followups": list(items)}, "https://github.com/fixture/repo/pull/7")
        day = time.strftime("%Y-%m-%d", time.localtime())
        return f"- {day} run {run_id} PR #7: "

    def test_a_follow_up_repeating_an_open_one_is_not_appended_again(self):
        logged = config.HOME / "followups" / "repo.md"
        logged.parent.mkdir(parents=True)
        opened = ["- 2026-09-01 run old PR #1: `a.py:1` - rename this - clarity",
                  "- 2026-09-01 run old PR #1: **the tick resumes a stopped run**",
                  "- c.py:3 - written by hand - clarity"]
        logged.write_text("".join(f"{line}\n" for line in opened))
        # the same `path:line` in other words, the same words: both are the note already open,
        # whether the loop or a hand wrote it, and so is a second item this run names at a
        # place it already named
        new = self.append("20260922-0000-repeat", "a.py:1 - add a test - coverage",
                          "**a.py:1 – rename it**", "**the tick resumes a stopped run**",
                          "c.py:3 - written by hand - clarity",
                          "b.py:2 - add a test - coverage", "`b.py:2` - add another - coverage")
        self.assertEqual(logged.read_text().splitlines(),
                         opened + [f"{new}b.py:2 - add a test - coverage"])

    def test_a_repository_has_one_follow_ups_file_whatever_the_case_of_its_name(self):
        directory = config.HOME / "followups"
        directory.mkdir(parents=True)
        (directory / "repo.md").write_text("- 2026-09-01 run a PR #1: a.py:1 - one - why\n"
                                           "- 2026-09-03 run c PR #3: c.py:3 - three - why\n")
        (directory / "REPO.md").write_text("- 2026-09-02 by hand: b.py:2 - two - why\n"
                                           "  and the reason, on a line of its own\n")
        (directory / "other.md").write_text("- 2026-09-02 run x PR #9: d.py:4 - four - why\n")
        new = self.append("20260922-0000-case", "b.py:2 - two again - why", "d.py:4 - four - why")
        self.assertEqual(sorted(path.name for path in directory.glob("*.md")),
                         ["other.md", "repo.md"])
        self.assertEqual((directory / "repo.md").read_text().splitlines(), [
            "- 2026-09-01 run a PR #1: a.py:1 - one - why",
            "- 2026-09-02 by hand: b.py:2 - two - why",
            "  and the reason, on a line of its own",
            "- 2026-09-03 run c PR #3: c.py:3 - three - why",
            f"{new}d.py:4 - four - why"])

    def test_past_24_kb_the_oldest_follow_ups_move_to_the_archive(self):
        directory = config.HOME / "followups"
        directory.mkdir(parents=True)
        # 192 lines of 128 bytes each: the file is exactly at its cap, not past it, and its
        # oldest entry is a bullet with a second line under it
        old = [f"- 2026-09-01 run old PR #1: f{n:03}.py:1 - {'x' * 87}" for n in range(192)]
        old[1] = f"  why: {'w' * 120}"
        (directory / "repo.md").write_text("".join(f"{line}\n" for line in old))
        self.assertEqual((directory / "repo.md").stat().st_size, run.FOLLOWUPS_CAP)
        new = self.append("20260922-0000-cap", "new.py:1 - newest - why")
        self.assertEqual((directory / "repo.archive.md").read_text(), f"{old[0]}\n{old[1]}\n")
        self.assertEqual((directory / "repo.md").read_text().splitlines(),
                         old[2:] + [f"{new}new.py:1 - newest - why"])
        # the archive only grows: every bullet that moved is still there, oldest first
        newer = self.append("20260922-0001-cap", "newer.py:1 - " + "y" * 300)
        kept = (directory / "repo.md").read_text()
        self.assertLessEqual(len(kept.encode()), run.FOLLOWUPS_CAP)
        self.assertEqual(((directory / "repo.archive.md").read_text() + kept).splitlines(),
                         old + [f"{new}new.py:1 - newest - why",
                                f"{newer}newer.py:1 - {'y' * 300}"])

    def test_a_rewrite_that_fails_leaves_every_file_as_it_was(self):
        directory = config.HOME / "followups"
        directory.mkdir(parents=True)
        files = {"repo.md": "- 2026-09-01 run a PR #1: a.py:1 - one - why\n",
                 "REPO.md": "- 2026-09-02 by hand: b.py:2 - two - why\n"}
        for name, text in files.items():
            (directory / name).write_text(text)
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            self.append("20260922-0000-full", "c.py:3 - three - why")
        self.assertEqual({path.name: path.read_text() for path in directory.glob("*.md")}, files)

    def test_appends_under_both_cases_of_a_name_keep_one_file_with_every_item(self):
        directory = config.HOME / "followups"
        directory.mkdir(parents=True)
        (directory / "REPO.md").write_text("- 2026-09-01 by hand: a.py:1 - one - why\n")
        url = "https://github.com/fixture/repo/pull/7"
        threads = [threading.Thread(target=run.append_followups, args=(
            {"run_id": f"race-{n}", "repo": str(self.root / name),
             "followups": [f"f{n}.py:1 - new - why"]}, url))
            for n, name in enumerate(["repo", "REPO"] * 4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        files = list(directory.glob("*.md"))
        self.assertEqual(len(files), 1, files)
        lines = files[0].read_text().splitlines()
        self.assertEqual(lines[0], "- 2026-09-01 by hand: a.py:1 - one - why")
        self.assertEqual(sorted(line.rsplit(": ", 1)[1] for line in lines[1:]),
                         sorted(f"f{n}.py:1 - new - why" for n in range(8)))


if __name__ == "__main__":
    unittest.main()
