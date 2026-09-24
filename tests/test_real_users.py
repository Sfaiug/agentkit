"""A new feature in a project with real users ships hidden, and only its reviewer is told.

Offline: one fake harness for every model records each prompt it is handed; the executor
writes the `AGENTS.md` front matter the case needs into a scratch run's workspace, so the
reviewer is judged on what the loop read off the work under review.  No git, GitHub,
Discord or real harness is reached, and no run marker of the caller's is inherited.
"""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, run, worker

RULE = f"{worker.GATE} {worker.REAL_USERS}"
ADAPTER = '''import json, os, pathlib, sys
root = pathlib.Path(os.environ["USERS_FIXTURE"])
if sys.argv[1] == "usage":
    print(json.dumps({"meters": [{"name": "weekly", "used": 0}]}))
    sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available":0}')
    sys.exit(0)
if sys.argv[1] != "run":
    sys.exit(2)
out = pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
with (root / "prompts.jsonl").open("a") as fh:
    fh.write(json.dumps(prompt) + "\\n")
role = "reviewer" if prompt.startswith("You are the reviewer") else "executor"
plan = root / "review-plan.json"
if role == "reviewer" and plan.exists():
    # a planned review: `silent` ends with no verdict and `background` with a command still
    # running, both with no session to resume, so the loop's follow-up is a new conversation
    modes = json.loads(plan.read_text())
    mode = modes.pop(0)
    plan.write_text(json.dumps(modes))
    if mode in ("silent", "background"):
        if mode == "background":
            (out / "stderr.log").write_text("Background tasks still running\\n")
        (out / "final.md").write_text("Still looking.")
        sys.exit(0)
    answer = "VERDICT: PASS\\n\\n## Findings\\n- none\\n"
elif role == "reviewer":
    seen = root / "reviewed"
    answer = ("VERDICT: PASS\\n\\n## Findings\\n- none\\n" if seen.exists() else
              "VERDICT: FAIL\\n\\n## Findings\\n- deliverable:1 - fixture - why it matters\\n")
    seen.touch()
else:
    front = root / "front.md"
    if front.exists():
        pathlib.Path(sys.argv[4], "AGENTS.md").write_text(front.read_text())
    pathlib.Path(sys.argv[4], "deliverable").write_text("fixture work\\n")
    answer = "## Summary\\nFixture work."
(out / "final.md").write_text(answer)
(out / "session_id").write_text("session-" + role)
'''


class RealUsers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".real-users-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(sockets), "TMUX": "",
            "NO_COLOR": "1", "PYTHONDONTWRITEBYTECODE": "1",
            config.ADAPTER_DIR_ENV: str(adapters), "USERS_FIXTURE": str(self.root)}))
        # the run under test is the only run here: a sweep must never find the caller's
        for inherited in (worker.RUN_MARKER, "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(inherited, None)
        self.script(bin_dir / "tmux", '''import sys
assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv
sys.exit(1)
''')
        for executable in ("gh", "claude", "codex", "muse"):
            self.script(bin_dir / executable, 'raise AssertionError("external call forbidden")\n')
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
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def launch(self, front, plan=None):
        """One scratch run, reviewed FAIL then PASS so a fixer runs, or as `plan` says; every
        prompt it handed out."""
        if front is not None:
            (self.root / "front.md").write_text(front)
        if plan is not None:
            (self.root / "review-plan.json").write_text(json.dumps(plan))
        task = self.root / "task.md"
        task.write_text("---\nrepo: none\n---\n# Users fixture\n\n"
                        "## Done when\n```bash\ntest -f deliverable\n```\n")
        before = set(run.run_dirs())
        code = run.main([str(task), "--exec", self.executor, "--review", self.reviewer])
        directory = (set(run.run_dirs()) - before).pop()
        self.assertEqual(code, 0, (directory / "log.txt").read_text())
        prompts = [json.loads(line) for line in
                   (self.root / "prompts.jsonl").read_text().splitlines()]
        reviews = [p for p in prompts if p.startswith("You are the reviewer")]
        others = [p for p in prompts if not p.startswith("You are the reviewer")]
        self.assertEqual(len(reviews), 2, prompts)
        if plan is None:
            self.assertTrue(any(p.startswith("You are the executor, continuing") for p in others))
        return reviews, others

    def test_front_matter_says_real_none_or_nothing(self):
        cases = {"---\nusers: real\ntests: python3 -m unittest\n---\n# Repo\n": "real",
                 "---\ntests: python3 -m unittest\nusers: none\n---\n# Repo\n": "none",
                 "---\nusers: real # production users\n---\n# Repo\n": "real",
                 "---\nusers: \"real\"\n---\n# Repo\n": "real",
                 "---\nusers: 'real'\n---\n# Repo\n": "real",
                 "---\nusers: \"none\"  # a hobby\n---\n# Repo\n": "none",
                 "---\nusers: # not asked yet\n---\n# Repo\n": None,
                 "---\ntests: python3 -m unittest\n---\n# Repo\n": None,
                 "# Repo\n\nusers: real in the body is not front matter\n": None,
                 None: None}
        for text, want in cases.items():
            with self.subTest(text=text):
                checkout = Path(tempfile.mkdtemp(dir=self.root))
                if text is not None:
                    (checkout / "AGENTS.md").write_text(text)
                self.assertEqual(run.users_declared(checkout), want)
        # the `tests:` command is a shell line, quotes and `#` included, and stays as written
        (checkout / "AGENTS.md").write_text(
            "---\nusers: 'real'\ntests: bash -c 'make check' # all of it\n---\n")
        self.assertEqual(run.declared(checkout, "tests"), "bash -c 'make check' # all of it")

    def test_a_real_users_reviewer_holds_the_hidden_feature_rule(self):
        for front in ("---\nusers: real\n---\n# Repo\n",
                      "---\nusers: \"real\"  # production users\n---\n# Repo\n"):
            with self.subTest(front=front):
                for leftover in ("prompts.jsonl", "reviewed"):
                    (self.root / leftover).unlink(missing_ok=True)
                reviews, others = self.launch(front)
                for prompt in reviews:
                    self.assertEqual(prompt.count(worker.REAL_USERS), 1)
                    self.assertIn(RULE, prompt)
                for prompt in others:
                    self.assertNotIn(worker.REAL_USERS, prompt)

    def test_a_none_or_unasked_repository_s_reviewer_is_not_given_the_rule(self):
        for front in ("---\nusers: none\n---\n# Repo\n", "# Repo\n", None):
            with self.subTest(front=front):
                for leftover in ("prompts.jsonl", "reviewed", "front.md"):
                    (self.root / leftover).unlink(missing_ok=True)
                reviews, others = self.launch(front)
                for prompt in reviews + others:
                    self.assertNotIn(worker.REAL_USERS, prompt)
                for prompt in reviews:
                    self.assertIn(worker.GATE, prompt)

    def test_a_follow_up_review_in_a_new_conversation_still_holds_the_rule(self):
        # The answer with no verdict and the turn left running in the background are each
        # followed up by an ask alone; with no session to resume, that ask opens a new
        # conversation, and the gate it carries is all that reviewer knows of the rule.
        for mode, ask in (("silent", run.NO_VERDICT_ASK),
                          ("background", f"{run.FINISH_IN_FOREGROUND} {run.NO_VERDICT_ASK}")):
            with self.subTest(mode=mode):
                (self.root / "prompts.jsonl").unlink(missing_ok=True)
                reviews, _ = self.launch("---\nusers: real\n---\n# Repo\n", [mode, "pass"])
                self.assertTrue(reviews[1].endswith(f"\n\n{ask}"), reviews[1][-300:])
                self.assertNotIn("# Users fixture", reviews[1])
                for prompt in reviews:
                    self.assertIn(RULE, prompt)

    def test_executor_and_fixer_prompts_are_the_same_whatever_users_says(self):
        seen = {}
        for users in ("real", "none"):
            for leftover in ("prompts.jsonl", "reviewed"):
                (self.root / leftover).unlink(missing_ok=True)
            before = set(run.run_dirs())
            reviews, others = self.launch(f"---\nusers: {users}\n---\n# Repo\n")
            run_id = (set(run.run_dirs()) - before).pop().name
            seen[users] = [prompt.replace(run_id, "<run>") for prompt in others]
        self.assertEqual(len(seen["real"]), 2)
        self.assertEqual(seen["real"], seen["none"])

    def test_the_rulebook_holds_the_question_the_planning_line_and_the_14_day_line(self):
        rulebook = (REPO / "orchestrator.md").read_text()
        sections = dict(re.findall(r"(?ms)^## (.+?)\n(.*?)(?=^## |\Z)", rulebook))
        for section, words in (
                ("Understand first", '"Does <project> have real users?"'),
                ("Understand first", "`No, straight to live`"),
                ("Understand first", "`Yes, new features stay hidden until I switch them on`"),
                ("Understand first", "`users: none` or `users: real`"),
                ("Decide and delegate", '"New feature: it stays hidden until you switch it on"'),
                ("Decide and delegate", "a `features:` command"),
                ("Housekeeping", "A feature on for everyone for more than 14 days has its switch "
                                 "removed from the code by your next task in that project.")):
            with self.subTest(words=words):
                self.assertIn(words, sections[section])
        self.assertLessEqual(len(rulebook.splitlines()), 55)


if __name__ == "__main__":
    unittest.main(verbosity=2)
