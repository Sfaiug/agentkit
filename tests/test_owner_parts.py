"""A change to the parts a repository names as the owner's lands only on the owner's yes.

Offline: a throwaway git repository whose AGENTS.md names `owner:` parts on its target branch,
changes cut from it, and ak's own delivery check and `ak run yes` against a throwaway state.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, owner, record as run_record, run

AGENTS = """---
owner: AGENTS.md#Vision, gate/, score.py
tests: python3 -m pytest
---
# repo

## Vision

Less.

## Lessons

- one
"""


def sh(wt, *args):
    return subprocess.run(["git", "-C", str(wt), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


class OwnerParts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.wt = self.home / "repo"
        self.wt.mkdir()
        sh(self.wt, "init", "-q", "-b", "main")
        sh(self.wt, "config", "user.email", "t@t")
        sh(self.wt, "config", "user.name", "t")
        self.write("AGENTS.md", AGENTS)
        self.write("gate/check.py", "x = 1\n")
        self.write("score.py", "y = 1\n")
        self.write("app.py", "z = 1\n")
        self.base = self.commit("base")
        sh(self.wt, "update-ref", "refs/remotes/origin/main", self.base)   # the target as fetched
        sh(self.wt, "checkout", "-q", "-b", "change")
        for name in ("STATE", "RUNS"):
            patcher = patch.object(config, name, self.home / name.lower())
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, path, text):
        (self.wt / path).parent.mkdir(parents=True, exist_ok=True)
        (self.wt / path).write_text(text)

    def commit(self, message):
        sh(self.wt, "add", "-A")
        sh(self.wt, "commit", "-q", "-m", message)
        return sh(self.wt, "rev-parse", "HEAD")

    def touched(self):
        return run.owner_parts(self.wt, "main", sh(self.wt, "rev-parse", "HEAD"))[1]

    def delivery(self):
        sha = sh(self.wt, "rev-parse", "HEAD")      # a passed review of this very commit
        return SimpleNamespace(wt=self.wt, run_dir=self.home / "runs" / "run-1", log=print,
                               write=lambda: None, state={"delivery_sha": sha, "review":
                                                          {"head_sha": sha},
                                                          "merge_method": "squash"})

    def test_each_named_part_is_touched_and_nothing_else(self):
        cases = [("app.py", "z = 2\n", []),
                 ("AGENTS.md", AGENTS.replace("- one", "- one\n- two"), []),
                 ("AGENTS.md", AGENTS.replace("Less.", "Fewer."), ["AGENTS.md#Vision"]),
                 ("AGENTS.md", AGENTS.replace("pytest", "pytest -x"), ["AGENTS.md front matter"]),
                 ("gate/new.py", "w = 1\n", ["gate"]),
                 ("score.py", "y = 2\n", ["score.py"])]
        for path, text, hit in cases:
            with self.subTest(path=path, hit=hit):
                sh(self.wt, "checkout", "-q", "-B", "change", self.base)
                self.write(path, text)
                self.commit(path)
                self.assertEqual(self.touched(), hit)

    def test_a_section_that_cannot_be_read_safely_is_the_rest_of_the_file(self):
        fenced = AGENTS.replace("Less.", "Less.\n\n```\n## not a heading\n```")
        sh(self.wt, "checkout", "-q", "-B", "change", self.base)
        self.write("AGENTS.md", fenced)
        self.commit("fence")
        self.assertEqual(self.touched(), ["AGENTS.md#Vision"])
        lessons = sh(self.wt, "rev-parse", "HEAD")
        self.write("AGENTS.md", fenced.replace("- one", "- one\n- two"))
        self.commit("lesson after a fence")
        self.assertIn("AGENTS.md#Vision",
                      owner.touched(self.wt, "AGENTS.md#Vision", lessons, "HEAD"))
        self.write("AGENTS.md", AGENTS.replace("## Vision", "## Aims"))
        self.commit("heading renamed")
        self.assertIn("AGENTS.md#Vision", self.touched())

    def test_a_delivery_waits_for_a_yes_to_exactly_that_content(self):
        self.write("score.py", "y = 2\n")
        self.commit("score")
        lp = self.delivery()
        with patch.object(run, "require_review_pass"), patch.object(run, "gh") as gh:
            self.assertFalse(run.do_merge(lp, "https://github.com/o/r/pull/1", "main"))
        gh.assert_not_called()
        self.assertTrue(lp.state["merge_failed"])
        self.assertIn("score.py", lp.state["merge_note"])
        self.assertIn("ak run yes run-1", lp.state["merge_note"])
        owner.say("run-1", owner.digest(self.wt, run.declared_at(self.wt, "main", "owner"),
                                        lp.state["delivery_sha"]))
        self.assertEqual(run.owner_unasked(lp, "main"), "")
        self.write("score.py", "y = 3\n")          # changed again after the yes: asked again
        self.commit("score again")
        self.assertIn("score.py", run.owner_unasked(self.delivery(), "main"))

    def test_only_the_target_names_the_parts(self):
        self.write("AGENTS.md", AGENTS.replace("owner: AGENTS.md#Vision, gate/, score.py\n", ""))
        self.write("score.py", "y = 2\n")
        self.commit("drop the guard and change a part")
        self.assertEqual(self.touched(), ["score.py", "AGENTS.md front matter"])
        sh(self.wt, "checkout", "-q", "-B", "main", self.base)
        self.write("AGENTS.md", AGENTS.replace("owner: AGENTS.md#Vision, gate/, score.py\n", ""))
        self.commit("main without an owner line")
        sh(self.wt, "checkout", "-q", "-b", "other")
        self.write("score.py", "y = 2\n")
        self.commit("score")
        self.assertEqual(self.touched(), [])

    def test_yes_is_kept_and_delivers_again_but_never_from_a_run(self):
        self.write("score.py", "y = 2\n")
        sha = self.commit("score")
        run_dir = config.RUNS / "run-1"
        run_dir.mkdir(parents=True)
        run_record.save_state(run_dir, {"run_id": "run-1", "state": "pass", "repo": str(self.wt),
                                        "target": "main", "delivery_sha": sha})
        with patch.dict(os.environ, {"AGENTKIT_RUN": str(run_dir)}):
            with self.assertRaisesRegex(config.Error, "a run cannot give it"):
                run.cmd_yes(["run-1"])
        self.assertIsNone(owner.said("run-1"))
        env = {k: v for k, v in os.environ.items() if k != "AGENTKIT_RUN"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(run, "cmd_resume", return_value=0) as resume:
            self.assertEqual(run.cmd_yes(["run-1"]), 0)
        resume.assert_called_once_with(["run-1", "--bg"])
        self.assertEqual(owner.said("run-1"),
                         owner.digest(self.wt, run.declared_at(self.wt, "main", "owner"), sha))


if __name__ == "__main__":
    unittest.main()
