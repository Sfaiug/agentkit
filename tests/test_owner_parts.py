"""A change to the parts a repository names as the owner's lands only on the owner's yes.

Offline: a throwaway git repository whose AGENTS.md names `owner:` parts on its target branch,
changes cut from it, and ak's delivery gate, `ak run yes` and `ak run no` against a throwaway
state. No real tmux, GitHub or network is touched.
"""

from contextlib import nullcontext
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
from agentkit import config, record as run_record, run

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
        sh(self.wt, "update-ref", "refs/remotes/origin/main", self.base)
        sh(self.wt, "checkout", "-q", "-b", "change")
        for name in ("STATE", "RUNS"):
            p = patch.object(config, name, self.home / name.lower())
            p.start()
            self.addCleanup(p.stop)

    def write(self, path, text):
        (self.wt / path).parent.mkdir(parents=True, exist_ok=True)
        (self.wt / path).write_text(text)

    def commit(self, message):
        sh(self.wt, "add", "-A")
        sh(self.wt, "commit", "-q", "-m", message)
        return sh(self.wt, "rev-parse", "HEAD")

    def touched(self):
        return run.owner_parts(self.wt, "origin/main", sh(self.wt, "rev-parse", "HEAD"))[1]

    # --- what a change touches ------------------------------------------------

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

    def test_a_section_is_read_as_a_reader_reads_it(self):
        # either fence holds a `## ` line inside the section; a change elsewhere is outside it.
        fenced = AGENTS.replace("Less.", "Less.\n\n~~~\n## not a heading\n~~~")
        sh(self.wt, "checkout", "-q", "-B", "change", self.base)
        self.write("AGENTS.md", fenced)
        self.commit("tilde fence in the vision")
        self.assertEqual(self.touched(), ["AGENTS.md#Vision"])
        base2 = sh(self.wt, "rev-parse", "HEAD")
        sh(self.wt, "update-ref", "refs/remotes/origin/main", base2)
        self.write("AGENTS.md", fenced.replace("- one", "- one\n- two"))
        self.commit("lessons after the fence")
        self.assertEqual(self.touched(), [])

    def test_a_declaration_read_from_the_target_ignores_a_shadowing_tag(self):
        sh(self.wt, "tag", "origin/main", self.base)   # a tag of the same name, pre-owner
        sh(self.wt, "checkout", "-q", "-B", "change", self.base)
        self.write("score.py", "y = 2\n")
        self.commit("score")
        self.assertEqual(run.owner_declaration(self.wt, "origin/main"),
                         "AGENTS.md#Vision, gate/, score.py")
        self.assertEqual(self.touched(), ["score.py"])

    def test_a_quoted_owner_value_still_protects_its_path(self):
        sh(self.wt, "checkout", "-q", "-B", "main", self.base)
        self.write("AGENTS.md", AGENTS.replace("owner: AGENTS.md#Vision, gate/, score.py",
                                               'owner: "score.py"'))
        quoted = self.commit("quote the owner value")
        sh(self.wt, "update-ref", "refs/remotes/origin/main", quoted)
        sh(self.wt, "checkout", "-q", "-b", "change2")
        self.write("score.py", "y = 2\n")
        self.commit("score")
        self.assertIn("score.py", run.owner_parts(self.wt, "origin/main",
                                                  sh(self.wt, "rev-parse", "HEAD"))[1])

    # --- the gate, the yes and the no ----------------------------------------

    def parked(self):
        """A run whose change touches score.py, taken to the gate; returns (lp, head)."""
        sh(self.wt, "checkout", "-q", "-B", "change", self.base)
        self.write("score.py", "y = 2\n")
        head = self.commit("score")
        run_dir = config.RUNS / "run-1"
        run_dir.mkdir(parents=True)
        lp = SimpleNamespace(wt=self.wt, run_dir=run_dir, log=lambda *a: None, write=lambda: None,
                             state={"delivery_sha": head, "session": "seat-x",
                                    "target": "main", "merge_method": "squash",
                                    "worktree": str(self.wt), "repo": str(self.wt)})
        run_record.save_state(run_dir, dict(lp.state, run_id="run-1", state="running"))
        return lp, head

    def gate(self, lp):
        cards = []
        with patch.object(run, "launch_session", return_value=None), \
             patch.object(run, "speaking_for", lambda state: nullcontext()), \
             patch.object(run.notify, "shaped",
                          side_effect=lambda kind, text, **kw: cards.append((kind, text, kw)) or 0):
            blocked = run.owner_block(lp, "origin/main")
        return blocked, cards

    def test_the_gate_parks_and_asks_the_owner_not_the_seat(self):
        lp, head = self.parked()
        blocked, cards = self.gate(lp)
        self.assertTrue(blocked)
        self.assertEqual(lp.state["state"], "waiting")          # resumable, not pass+merge_failed
        self.assertEqual(lp.state["waiting_on"], {"owner": head})
        self.assertFalse(lp.state.get("merge_failed"))
        self.assertEqual(len(cards), 1)                         # the owner is asked, once
        kind, text, kw = cards[0]
        self.assertEqual(kind, "needs")
        self.assertEqual(kw.get("session"), "seat-x")          # the launching seat's owner card
        self.assertIn("score.py", text)
        self.assertIn("ak run yes run-1", text)

    def test_yes_records_the_content_and_delivers_again(self):
        lp, head = self.parked()
        self.gate(lp)
        run_record.save_state(lp.run_dir, {**run_record.read_state(lp.run_dir),
                                           "state": "waiting", "waiting_on": {"owner": head}})
        with patch.object(run, "cmd_resume", return_value=0) as resume:
            self.assertEqual(run.cmd_yes(["run-1"]), 0)
        resume.assert_called_once_with(["run-1", "--bg"])
        self.assertFalse(self.gate(lp)[0])                      # the gate now passes
        self.assertEqual(run.owner_said("run-1"), run.owner_digest(
            self.wt, head, run.owner_declaration(self.wt, "origin/main")))
        self.write("score.py", "y = 3\n")                      # a later change asks again
        self.commit("score again")
        lp.state["delivery_sha"] = sh(self.wt, "rev-parse", "HEAD")
        self.assertTrue(self.gate(lp)[0])

    def test_no_keeps_the_branch_unmerged(self):
        lp, head = self.parked()
        self.gate(lp)
        run_record.save_state(lp.run_dir, {**run_record.read_state(lp.run_dir),
                                           "state": "waiting", "waiting_on": {"owner": head}})
        self.assertEqual(run.cmd_no(["run-1"]), 0)
        state = run_record.read_state(lp.run_dir)
        self.assertEqual(state["state"], "blocked")
        self.assertNotIn("waiting_on", state)
        self.assertIsNone(run.owner_said("run-1"))

    def test_yes_and_no_refuse_inside_a_run(self):
        lp, head = self.parked()
        run_record.save_state(lp.run_dir, {**run_record.read_state(lp.run_dir),
                                           "state": "waiting", "waiting_on": {"owner": head}})
        with patch.dict(os.environ, {"AGENTKIT_RUN": str(lp.run_dir)}):
            for verb, fn in (("yes", run.cmd_yes), ("no", run.cmd_no)):
                with self.subTest(verb=verb), self.assertRaisesRegex(config.Error, "a run cannot"):
                    fn(["run-1"])


if __name__ == "__main__":
    unittest.main()
