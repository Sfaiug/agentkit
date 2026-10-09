"""A seat's own pull request under review, offline.

A real repository with the PR branch and a bare remote the run pushes to, which is what
GitHub reports as the PR's head; GitHub itself, the reviewer, the fixer, seats and processes
are fakes.  The fixer adopts the next of the commits prepared on the PR branch, so each fix is
a known head; a test that wants another fix overrides `fix`.
"""

from contextlib import ExitStack, nullcontext, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from fixtures.landing import landing
from agentkit import gate, hand_in, host, config, gc, orch, run, status, watch, worker
from agentkit import record

URL = "https://github.com/acme/widget/pull/7"
BRANCH = "fix-api"


class OwnPr(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-own-pr-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "fix-api",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "NO_COLOR": "1"}))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        config.ensure_dirs()
        self.cfg = config.load()
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"])
        self.remote = self.root / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main", str(self.remote)],
                       check=True)
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@localhost")
        self.git("remote", "add", "origin", str(self.remote))
        (self.repo / "AGENTS.md").write_text("---\nusers: none\ntests: test -f fence.txt\n---\n# acme\n")
        (self.repo / "fence.txt").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Base")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-qb", BRANCH)
        self.heads = []
        for n in range(1, 5):
            (self.repo / "fence.txt").write_text(f"fix {n}\n" * (5000 if n > 1 else 1))
            self.git("commit", "-qam", f"Fix {n}")
            self.heads.append(self.git("rev-parse", "HEAD"))
        self.git("push", "-q", "origin", f"{self.heads[0]}:refs/heads/{BRANCH}")
        self.pr = {"state": "OPEN", "title": "Mend the fence", "author": "owner",
                   "baseRefName": "main", "body": "Fix the fence"}
        self.run_dir = config.RUNS / "own-pr-rounds"
        self.run_dir.mkdir()
        (self.run_dir / "log.txt").touch()
        run.capture_launch(self.run_dir, {"--review-pr": URL})
        self.prompts, self.fixes, self.notices, self.events, self.merges = [], [], [], [], []
        self.reviewers, self.fix_names = [], []
        self.fix_summary = "## Summary\nFixed."
        self.verdicts = []
        for name, value in (("viewer_login", "owner"), ("checkout_for", self.repo),
                            ("fetch", (0, "")),
                            ("collect_usage", {}), ("checks", (True, "")),
                            ("process_active", True), ("scope_alive", None),
                            ("host_status_line", "fixture host")):
            self.stack.enter_context(patch.object(record if name == "process_active" else
                                                gate if name == "host_status_line" else
                                                status if name == "scope_alive" else run,
                                                name, return_value=value))
        self.stack.enter_context(patch.object(gc, "disk_pressure", return_value=False))
        self.stack.enter_context(patch.object(run, "pr_view", side_effect=self.view))
        self.stack.enter_context(patch.object(run, "gh_json", side_effect=self.gh_json))
        self.stack.enter_context(patch.object(run, "gh", side_effect=self.gh))
        self.stack.enter_context(patch.object(run, "join_line", side_effect=lambda lp, _upstream, deliver:
                                             landing(lp, deliver=deliver)))
        self.stack.enter_context(patch.object(run, "merge_lock", side_effect=lambda *a, **k: nullcontext()))
        self.stack.enter_context(patch.object(worker, "call", side_effect=submitting(self.reviewer)))
        self.stack.enter_context(patch.object(run, "execute", side_effect=self.fixer))
        self.stack.enter_context(patch.object(run, "launcher_world", side_effect=lambda *a, **k: nullcontext(True)))
        self.stack.enter_context(patch.object(orch, "find", return_value={"name": "fix-api"}))
        self.stack.enter_context(patch.object(watch, "type_at_prompt", side_effect=self.tell))
        self.stack.enter_context(patch.object(host, "frozen_cgroup", return_value=None))
        self.stack.enter_context(patch.object(watch, "step_for_run", return_value=("none", "no child", None, [])))
        self.kill = self.stack.enter_context(patch.object(watch, "kill_tree"))
        self.resume = self.stack.enter_context(patch.object(watch, "launch_resume"))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def remote_head(self):
        """The PR's head as GitHub would report it: what the remote branch holds."""
        return subprocess.run(["git", "-C", str(self.remote), "rev-parse", BRANCH], check=True,
                              capture_output=True, text=True).stdout.strip()

    def hand_push(self, n):
        """The seat pushes one of the prepared commits by hand."""
        self.git("push", "-q", "--force", "origin", f"{self.heads[n]}:refs/heads/{BRANCH}")

    def view(self, _url):
        return {**self.pr, "headRefOid": self.remote_head()}

    def gh(self, cwd, *args, **_kw):
        if args[:2] == ("pr", "merge"):
            self.merges.append(args)
        if args[0] == "api":
            self.events.append(args[args.index("-f") + 3])
        return 0, ""

    def gh_json(self, _cwd, *args, **_kw):
        if args[:2] == ("api", "repos/acme/widget/pulls/7"):
            return {"state": self.pr["state"].lower(), "merged": self.pr["state"] == "MERGED",
                    "body": self.pr["body"],
                    "head": {"sha": self.remote_head(), "ref": BRANCH,
                             "repo": {"clone_url": str(self.remote)}},
                    "base": {"ref": "main"}}, ""
        return self.view(URL), ""

    def tell(self, seat, line, *args, **_kw):
        self.notices.append(line)
        return True

    def reviewer(self, cfg, name, body, workspace, out_dir, role, session, **_kw):
        self.prompts.append(body)
        self.reviewers.append(name)
        n = len(self.prompts)
        self.assertLessEqual(n, len(self.verdicts), "reviewed a head twice")
        self.assertEqual(run.git(workspace, "rev-parse", "HEAD"), self.remote_head())
        verdict = self.verdicts[n - 1]
        text = (f"## Findings\n- fence.txt:1 - defect {n} - wrong edge outcome\n"
                if verdict == "FAIL" else "## Findings\n- none\n") + f"VERDICT: {verdict}\n"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "final.md").write_text(text)
        return 0, text, f"review-{n}", False

    def fix(self, lp):
        """What the fixer leaves in the checkout: the next prepared commit, by default, on the
        reviewed head it was given."""
        self.assertEqual(run.git(lp.wt, "rev-parse", "HEAD"), lp.state["head_sha"])
        run.git(lp.wt, "reset", "--hard", self.heads[len(self.fixes)])

    def fixer(self, lp, role, text, name):
        """The turn as execute() records it: its directory opened before the work, closed after."""
        self.assertEqual(role, "fixer")
        self.assertEqual(record.read_state(self.run_dir)["state"], "running")
        self.fix_names.append(name)
        out = run.free_dir(lp, name)
        out.mkdir(parents=True)
        (out / hand_in.FILE).write_text(json.dumps(
            {"kind": "turn", "workspace": str(lp.wt), "role": role, "findings": []}) + "\n")
        self.fixes.append(text)
        self.fix(lp)                    # may raise: the host cut the turn off
        with (out / hand_in.FILE).open("a") as handle:
            handle.write(json.dumps({"kind": "done"}) + "\n")
        (out / "final.md").write_text(self.fix_summary)
        return self.fix_summary

    def review(self, verdicts):
        self.verdicts = verdicts
        return run.review_pr(self.cfg, self.run_dir, URL,
                             {"--review": None, "--review-pr": URL}, lambda _: None)
