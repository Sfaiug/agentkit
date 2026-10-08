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
from agentkit import config, notify, owner, record as run_record, run, watch
from fixtures.sandbox import Sandbox

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


class OwnerParts(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_RUN_ROLE": "",
            "AK_NOTIFY_SINK": "off", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1"}))
        self.home = self.root
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
        self.target(self.base)
        sh(self.wt, "remote", "add", "origin", str(self.wt))
        sh(self.wt, "checkout", "-q", "-b", "change")
        self.stack.enter_context(patch.object(run, "gh_json", side_effect=self.target_api))

    def target(self, sha):
        sh(self.wt, "update-ref", "refs/heads/main", sha)
        sh(self.wt, "update-ref", "refs/remotes/origin/main", sha)

    def target_api(self, _cwd, *args, **_kw):
        self.assertEqual(args, ("api", "repos/acme/widget/git/ref/heads/main"))
        return {"object": {"type": "commit", "sha": sh(self.wt, "rev-parse", "refs/heads/main")}}, ""

    def write(self, path, text):
        (self.wt / path).parent.mkdir(parents=True, exist_ok=True)
        (self.wt / path).write_text(text, encoding="utf-8", errors="surrogateescape")

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

    def test_a_section_holding_a_fence_is_protected_to_the_end_of_the_file(self):
        # A section that holds either fence marker runs to the end of the file: fence parsing is
        # not relied on to find where it ends, so a change anywhere below it needs the owner's yes.
        fenced = AGENTS.replace("Less.", "Less.\n\n~~~\n## not a heading\n~~~")
        sh(self.wt, "checkout", "-q", "-B", "change", self.base)
        self.write("AGENTS.md", fenced)
        self.commit("tilde fence in the vision")
        self.assertEqual(self.touched(), ["AGENTS.md#Vision"])
        base2 = sh(self.wt, "rev-parse", "HEAD")
        self.target(base2)
        self.write("AGENTS.md", fenced.replace("- one", "- one\n- two"))
        self.commit("lessons after the fence")
        self.assertEqual(self.touched(), ["AGENTS.md#Vision"])

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
        self.target(quoted)
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
                                    "pr": "https://github.com/acme/widget/pull/1",
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
            self.assertEqual(run.cmd_yes(["run-1", head[:12]]), 0)
        resume.assert_called_once_with(["run-1", "--bg"])
        self.assertFalse(self.gate(lp)[0])                      # the gate now passes
        self.assertEqual(run.owner_said("run-1"), run.owner_digest(
            self.wt, head, run.owner_target_parts(self.wt, "origin/main")))
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

    def test_yes_refuses_a_stale_or_missing_key(self):
        lp, head = self.parked()
        self.gate(lp)
        run_record.save_state(lp.run_dir, {**run_record.read_state(lp.run_dir),
                                           "state": "waiting", "waiting_on": {"owner": head}})
        for argv in (["run-1"], ["run-1", "deadbeef0000"]):
            with self.subTest(argv=argv), self.assertRaisesRegex(config.Error, "waiting on key"):
                run.cmd_yes(argv)

    def test_a_trailing_comment_and_a_block_form_do_not_drop_the_guard(self):
        # a trailing `# comment` is not a heading
        sh(self.wt, "checkout", "-q", "-B", "main", self.base)
        self.write("AGENTS.md", AGENTS.replace("owner: AGENTS.md#Vision, gate/, score.py",
                                               "owner: score.py  # the scoreboard"))
        commented = self.commit("comment the owner value")
        self.target(commented)
        self.assertEqual(run.owner_declaration(self.wt, "origin/main"), "score.py")
        sh(self.wt, "checkout", "-q", "-b", "c1"); self.write("score.py", "y = 2\n"); self.commit("s")
        self.assertEqual(run.owner_parts(self.wt, "origin/main",
                                         sh(self.wt, "rev-parse", "HEAD"))[1], ["score.py"])
        # a block-form owner value names nothing flat, so the front matter is protected (fail closed)
        sh(self.wt, "checkout", "-q", "-B", "main", commented)
        self.write("AGENTS.md", AGENTS.replace("owner: AGENTS.md#Vision, gate/, score.py",
                                               "owner:\n  - score.py"))
        block = self.commit("block-form owner")
        self.target(block)
        self.assertEqual(run.owner_target_parts(self.wt, "origin/main"),
                         [("AGENTS.md", owner.FRONT)])

    def test_a_replace_ref_does_not_hide_a_change(self):
        old = self.base
        sh(self.wt, "checkout", "-q", "-B", "change", self.base)
        self.write("score.py", "y = 2\n")
        head = self.commit("score")
        sh(self.wt, "replace", head, old)        # a planted replacement of the head with the base
        self.assertEqual(self.touched(), ["score.py"])
        sh(self.wt, "replace", "-d", head)

    def test_a_duplicate_protected_heading_is_covered_to_the_end(self):
        doc = AGENTS + "\n## Vision\n\nMore, appended.\n"
        self.assertIn("More, appended.", owner.piece(doc, "Vision"))

    def test_a_section_with_a_fence_runs_to_the_end_of_the_file(self):
        doc = "## Vision\n\n```\n~~~\n## inside\n```\n\n## After\n\nx\n"
        section = owner.piece(doc, "Vision")
        self.assertIn("## inside", section)
        self.assertIn("## After", section)        # a fenced section is protected to the end

    def test_a_section_named_by_a_literal_dashes_heading_is_not_the_front_matter(self):
        # `file#---` names the `## ---` section, not the file's front matter: a change there is a hit.
        doc = "---\ntitle: acme\n---\n## ---\nOwner policy\n## Public\nApp notes\n"
        section = owner.piece(doc, "---")
        self.assertIn("Owner policy", section)
        self.assertNotIn("title: acme", section)  # not the front matter
        changed = owner.piece(doc.replace("Owner policy", "Changed policy"), "---")
        self.assertNotEqual(section, changed)

    def test_a_replace_ref_does_not_hide_an_added_owner_file(self):
        # The owner names a file absent at the base; the branch adds it, then a replace ref swaps the
        # head for the base so a lookup with replacements on reads it absent at both revisions.
        sh(self.wt, "checkout", "-q", "-B", "main", self.base)
        self.write("AGENTS.md", AGENTS.replace("owner: AGENTS.md#Vision, gate/, score.py",
                                               "owner: guard.txt"))
        base2 = self.commit("owner names a not-yet-present file")
        self.target(base2)
        sh(self.wt, "checkout", "-q", "-b", "add-guard")
        self.write("guard.txt", "owner content\n")
        head = self.commit("add the protected file")
        self.assertIn("guard.txt", run.owner_parts(self.wt, "origin/main", head)[1])
        sh(self.wt, "replace", head, base2)
        self.assertIn("guard.txt", run.owner_parts(self.wt, "origin/main", head)[1])
        sh(self.wt, "replace", "-d", head)

    def test_an_owner_file_turned_into_a_symlink_is_a_change(self):
        # A regular file becomes a symlink to a same-named file with other content: the blob id is
        # unchanged, but the entry mode is part of the identity, so it is a change.
        sh(self.wt, "checkout", "-q", "-B", "change", self.base)
        self.write("locked", "open\n")
        (self.wt / "score.py").unlink()
        (self.wt / "score.py").symlink_to("locked")
        self.commit("score.py becomes a symlink")
        self.assertIn("score.py", self.touched())

    def test_an_unreadable_declaration_stops_delivery(self):
        sh(self.wt, "checkout", "-q", "-B", "change", self.base)
        self.write("score.py", "y = 2\n")
        self.commit("score")
        oid = sh(self.wt, "rev-parse", "refs/remotes/origin/main:AGENTS.md")
        (self.wt / ".git/objects" / oid[:2] / oid[2:]).unlink()
        with self.assertRaises(config.Error):
            run.owner_parts(self.wt, "origin/main", sh(self.wt, "rev-parse", "HEAD"))

    def test_an_unreadable_owner_tree_stops_delivery(self):
        # An added owner file whose parent tree object git cannot read: a failed read is not an
        # absent entry, so delivery stops rather than dropping the guard.
        sh(self.wt, "checkout", "-q", "-B", "main", self.base)
        self.write("AGENTS.md", AGENTS.replace("owner: AGENTS.md#Vision, gate/, score.py",
                                               "owner: policy/rules.txt"))
        base2 = self.commit("owner names a nested file")
        self.target(base2)
        sh(self.wt, "checkout", "-q", "-b", "addrules")
        self.write("policy/rules.txt", "new owner rules")
        head = self.commit("add rules")
        oid = sh(self.wt, "rev-parse", head + ":policy")
        (self.wt / ".git/objects" / oid[:2] / oid[2:]).unlink()
        with self.assertRaises(config.Error):
            run.owner_parts(self.wt, "origin/main", head)

    def test_a_non_ascii_or_tab_owner_path_is_detected(self):
        # Git C-quotes such names in plain ls-tree; read with -z they keep their exact bytes, so a
        # change to a café.txt or a tab-bearing owner path is seen, not read as absent.
        for path in ("café.txt", "policy\tfile.txt"):
            with self.subTest(path=path):
                sh(self.wt, "checkout", "-q", "-B", "main", self.base)
                self.write("AGENTS.md", AGENTS.replace(
                    "owner: AGENTS.md#Vision, gate/, score.py", f"owner: {path}"))
                self.write(path, "locked")
                based = self.commit("owner names a quoted path")
                self.target(based)
                sh(self.wt, "checkout", "-q", "-B", "change", based)
                self.write(path, "open")
                head = self.commit("change the quoted path")
                self.assertIn(path, run.owner_parts(self.wt, "origin/main", head)[1])

    def test_a_second_runs_owner_question_stays_visible_after_the_first_is_answered(self):
        # Two runs from one seat each wait on the owner; a session carries one notice at a time.
        # Answering one must resurface the other, so a pending approval is never hidden.
        from agentkit import notify
        sh(self.wt, "checkout", "-q", "-B", "change", self.base)
        self.write("score.py", "y = 2\n")
        head = self.commit("score")
        config.ensure_dirs()
        config.session_path("seat-x").write_text("{}")
        dirs = []
        for name in ("run-a", "run-b"):
            rd = config.RUNS / name
            rd.mkdir(parents=True)
            lp = SimpleNamespace(wt=self.wt, run_dir=rd, log=lambda *a: None,
                                 write=lambda rd=rd: None,
                                 state={"run_id": name, "delivery_sha": head, "session": "seat-x",
                                        "launched_session": "seat-x", "target": "main",
                                        "merge_method": "squash", "worktree": str(self.wt),
                                        "repo": str(self.wt)})
            with patch.object(run, "launch_session", return_value="seat-x"), \
                    patch.object(notify, "transition", return_value=0):
                self.assertTrue(run.owner_block(lp, "origin/main"))
            run_record.save_state(rd, {**lp.state, "state": "waiting", "finished_at": 1.0,
                                       "waiting_on": {"owner": head}})
            dirs.append(rd)
        self.assertIn("owner:run-b:", notify.last("seat-x")["source"])
        with patch.object(run, "launch_session", return_value="seat-x"), \
                patch.object(notify, "transition", return_value=0):
            run.cmd_no(["run-b"])
        resurfaced = notify.last("seat-x")
        self.assertIsNotNone(resurfaced)
        self.assertIn("owner:run-a:", resurfaced["source"])   # the first run's approval is back

    def test_a_declared_owner_key_is_accepted_front_matter(self):
        # rules_check reads the owner key, so a project's first owner declaration lands.
        self.assertEqual(run.unknown_front_lines(AGENTS), [])

    def test_yes_and_no_refuse_inside_a_run(self):
        lp, head = self.parked()
        run_record.save_state(lp.run_dir, {**run_record.read_state(lp.run_dir),
                                           "state": "waiting", "waiting_on": {"owner": head}})
        with patch.dict(os.environ, {"AGENTKIT_RUN": str(lp.run_dir)}):
            for verb, fn in (("yes", run.cmd_yes), ("no", run.cmd_no)):
                with self.subTest(verb=verb), self.assertRaisesRegex(config.Error, "a run cannot"):
                    fn(["run-1"])

    def test_a_nul_cannot_move_part_metadata_and_reuse_an_owner_yes(self):
        sh(self.wt, "checkout", "-q", "-B", "change", self.base)
        self.write("AGENTS.md", "---\nowner: a.md#Vision, b.md#Vision\n---\n# acme\n")
        self.write("a.md", "## Vision\nlocked a\n")
        self.write("b.md", "## Vision\nlocked b\n")
        self.target(self.commit("owner sections"))
        marker = "\0" + repr(("b.md", "Vision", False)) + "\0" + "100644\0"
        a, b, tail = "## Vision\nalpha\n", "## Vision\nbeta\n", "## Vision\ngamma\n"
        self.write("a.md", a)
        self.write("b.md", b + marker + tail)
        approved = self.commit("reviewed owner sections")
        lp, _ = self.parked_at(approved)
        self.assertTrue(self.gate(lp)[0])
        run_record.save_state(lp.run_dir, {**lp.state, "run_id": lp.run_dir.name})
        with patch.object(run, "cmd_resume", return_value=0):
            run.cmd_yes([lp.run_dir.name, approved[:12]])
        parts = run.owner_target_parts(self.wt, "origin/main")
        self.write("a.md", a + marker + b)
        self.write("b.md", tail)
        changed = self.commit("move delimiter and metadata between sections")
        self.assertNotEqual(run.owner_contents(self.wt, approved, parts),
                            run.owner_contents(self.wt, changed, parts))
        self.assertNotEqual(run.owner_digest(self.wt, approved, parts),
                            run.owner_digest(self.wt, changed, parts))
        lp.state["delivery_sha"] = changed
        self.assertTrue(self.gate(lp)[0])

    def parked_at(self, head):
        directory = config.RUNS / "run-1"
        directory.mkdir(exist_ok=True)
        state = {"run_id": directory.name, "delivery_sha": head, "session": "seat-x",
                 "launched_session": "seat-x", "target": "main", "merge_method": "squash",
                 "worktree": str(self.wt), "repo": str(self.wt), "started_at": 9990,
                 "pr": "https://github.com/acme/widget/pull/1"}
        lp = SimpleNamespace(wt=self.wt, run_dir=directory, state=state, cfg={},
                             log=lambda *_: None, write=lambda: run_record.save_state(directory, state))
        lp.write()
        return lp, head

    def test_digest_distinguishes_all_fields_and_absent_content(self):
        cases = [("a", None, None), ("a", None, ""), ("a", "", ""),
                 ("a\0b", "c", "d"), ("a", "b\0c", "d"),
                 ("a", "b", "c\0d"), ("a", "b", "c\udc80d")]
        self.assertEqual(len({owner.digest([case]) for case in cases}), len(cases))
        self.assertNotEqual(owner.digest(cases), owner.digest(cases[::-1]))
        self.assertNotEqual(owner.digest([]), owner.digest([("", None, None)]))

    def test_invalid_utf8_names_cannot_shadow_a_protected_entry(self):
        for protected in ("policy\ufffd.txt", os.fsdecode(b"policy\x81.txt")):
            with self.subTest(protected=protected):
                sh(self.wt, "checkout", "-q", "-B", "change", self.base)
                self.write("AGENTS.md", f"---\nowner: {protected}\n---\n# acme\n")
                self.write(protected, "locked")
                self.write(os.fsdecode(b"policy\x80.txt"), "unchanged unowned file")
                self.target(self.commit("byte-distinct filenames"))
                self.write(protected, "open")
                self.commit("change the protected file")
                self.assertIn(protected, self.touched())

    def session_answer(self, records):
        return watch.session_state("seat-x", session={"name": "seat-x"}, records=records,
            cfg={"models": {}, "providers": {}}, live={"state": "at_prompt"}, harness="codex",
            auth_out={}, gh_out={}, token_out={}, waits=False, silent={})

    def test_an_unrelated_prompt_or_restart_cannot_hide_owner_approval(self):
        lp, head = self.parked()
        lp.state["launched_session"] = "seat-x"
        config.session_path("seat-x").write_text("{}")
        with patch.object(notify, "transition", return_value=0):
            self.assertTrue(run.owner_block(lp, "origin/main"))
        lp.state["finished_at"] = 9990
        run_record.save_state(lp.run_dir, lp.state)
        notify.answered("seat-x", 10001)
        self.assertIsNotNone(notify.last("seat-x"))
        notify.opened("seat-x", lambda: "before")
        notify.progress("seat-x", lambda: "after", None)
        records = [(lp.run_dir, run_record.read_state(lp.run_dir))]
        for replaced in (False, True):
            with self.subTest(replaced=replaced), patch.object(run, "launcher_watched", return_value=True):
                if replaced:
                    config.notify_path("seat-x").unlink()
                answer = self.session_answer(records)
                self.assertTrue(answer.get("question"), answer)
                self.assertIn(f"ak run yes {lp.run_dir.name} {head[:12]}", answer["reason"])
        with patch.object(run, "cmd_resume", return_value=0):
            run.cmd_yes([lp.run_dir.name, head[:12]])
        with patch.object(run, "launcher_watched", return_value=True):
            self.assertFalse(self.session_answer([(lp.run_dir, run_record.read_state(lp.run_dir))]).get("question"))

    def test_direct_owner_test_leaves_the_callers_home_empty(self):
        caller = self.root / "caller"
        caller.mkdir()
        result = subprocess.run([sys.executable, "-B", __file__,
            "OwnerParts.test_a_second_runs_owner_question_stays_visible_after_the_first_is_answered"],
            env={**os.environ, "HOME": str(caller), "TMPDIR": str(self.root)},
            capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(list(caller.rglob("*")), [])


if __name__ == "__main__":
    unittest.main()
