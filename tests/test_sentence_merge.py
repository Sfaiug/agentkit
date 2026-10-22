"""Markdown merges sentence by sentence wherever ak merges: the lease scan and a rebase.

Two edits of one paragraph's line that change different sentences, neighbours included, merge,
so the scan parks nobody and a rebase onto the moved base finishes with both; two edits of one
sentence still clash as git's line merge has them, markers included.  The cut is undone byte
for byte.  Every other path keeps the attributes this call's git reads, as it reads them now,
and the lookup runs under the call's timeout.  Offline: the lease stage (`fixtures.leases`), a
real repository.
"""

import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import OLDER, YOUNGER, LiveRuns
from agentkit import gitcall, leases, sentences

PARAGRAPH = ("# Widget\n\nThe first sentence says one thing. The second says another! "
             "Does the third ask? The fourth ends it.\n")


class SentenceMerge(LiveRuns):
    def setUp(self):
        super().setUp()
        (self.repo / "README.md").write_text(PARAGRAPH)
        self.git(self.repo, "add", "README.md")
        self.git(self.repo, "commit", "-qm", "Docs")
        self.base = self.git(self.repo, "rev-parse", "HEAD")

    def change(self, checkout, old, new):
        readme = checkout / "README.md"
        readme.write_text(readme.read_text().replace(old, new))
        self.git(checkout, "commit", "-qam", f"README: {new}")

    def building(self, name, started):
        return self.run_on(name, started, step="executor", rounds=0)

    def test_edits_of_different_sentences_of_one_line_park_nobody(self):
        self.change(self.building(OLDER, 900), "first sentence", "first sentence, older,")
        self.change(self.building(YOUNGER, 1000), "fourth ends", "fourth, younger, ends")
        found = leases.scan(self.repo, self.logs.append, now=2000)
        self.assertNotIn(YOUNGER, found)
        self.assertEqual(self.state(YOUNGER)["state"], "running")

    def test_edits_of_neighbouring_sentences_park_nobody(self):
        self.change(self.building(OLDER, 900), "first sentence", "first sentence, older,")
        self.change(self.building(YOUNGER, 1000), "second says", "second, younger, says")
        self.assertNotIn(YOUNGER, leases.scan(self.repo, self.logs.append, now=2000))

    def test_a_rebase_onto_a_moved_paragraph_keeps_both_sentences(self):
        branch = self.run_on(YOUNGER, 1000)
        self.change(branch, "third ask", "third ask the branch")
        self.change(self.repo, "first sentence", "first sentence on main")
        code, out = gitcall.git_out(branch, "rebase", "main")
        self.assertEqual(code, 0, out)
        self.assertEqual((branch / "README.md").read_text(), PARAGRAPH.replace(
            "first sentence", "first sentence on main").replace("third ask", "third ask the branch"))

    def test_a_rebase_keeps_edits_of_neighbouring_sentences(self):
        branch = self.run_on(YOUNGER, 1000)
        self.change(branch, "second says", "second, the branch's, says")
        self.change(self.repo, "first sentence", "first sentence on main")
        code, out = gitcall.git_out(branch, "rebase", "main")
        self.assertEqual(code, 0, out)
        self.assertEqual((branch / "README.md").read_text(), PARAGRAPH.replace(
            "first sentence", "first sentence on main").replace("second says", "second, the branch's, says"))

    def test_a_rebase_behind_git_s_own_options_keeps_both_sentences(self):
        branch = self.run_on(YOUNGER, 1000)
        self.change(branch, "fourth ends", "fourth, the branch's, ends")
        self.change(self.repo, "first sentence", "first sentence on main")
        code, out = gitcall.git_out(branch, "-c", "rebase.updateRefs=false", "rebase", "main")
        self.assertEqual(code, 0, out)
        self.assertEqual((branch / "README.md").read_text(), PARAGRAPH.replace(
            "first sentence", "first sentence on main").replace("fourth ends", "fourth, the branch's, ends"))

    def test_a_clash_inside_one_sentence_stops_the_rebase_with_line_markers(self):
        branch = self.run_on(YOUNGER, 1000)
        self.change(branch, "second says", "second, the branch's, says")
        self.change(self.repo, "says another", "says main's word")
        code, _ = gitcall.git_out(branch, "rebase", "main")
        self.assertNotEqual(code, 0)
        text = (branch / "README.md").read_text()
        self.assertIn("<<<<<<< current\n", text)
        self.assertIn(">>>>>>> incoming\n", text)
        self.assertIn("The first sentence says one thing. The second, the branch's, says another!", text)
        gitcall.git_out(branch, "rebase", "--abort")

    def test_the_cut_is_undone_byte_for_byte(self):
        for text in (PARAGRAPH, "No end", "Two.  Spaces.\r\nCRLF! \"Quoted.\" Next\n", "a. b. c.",
                     "Ends with a stop. ", "*Emphasis.* Then `code.` then (aside.) more.\n", ""):
            self.assertEqual(sentences.joined(sentences.cut(text)), text)
        self.assertEqual(sentences.cut("One. Two"), "One. \n" + sentences.MARK + "\nTwo")

    def test_every_other_path_keeps_the_attributes_this_git_reads_now(self):
        own = self.root / "attributes"
        own.write_text("*.dat -merge\n")
        self.git(self.repo, "config", "core.attributesFile", str(own))

        def merging(*paths):
            env = gitcall.merge_config(["git", "-C", str(self.repo)], None, dict(os.environ), 5)
            return subprocess.run(["git", "-C", str(self.repo), "check-attr", "merge", "--", *paths],
                                  env=env, check=True, capture_output=True, text=True).stdout

        self.assertEqual(merging("data.dat", "README.md"),
                         "data.dat: merge: unset\nREADME.md: merge: ak-sentences\n")
        own.write_text("*.dat merge=union\n*.md merge=union\n")
        self.assertEqual(merging("data.dat", "README.md"),
                         "data.dat: merge: union\nREADME.md: merge: union\n")

    def test_the_attributes_lookup_runs_under_the_call_s_timeout(self):
        calls, real = [], subprocess.run

        def recording(cmd, **kwargs):
            calls.append((cmd, kwargs.get("timeout")))
            return real(cmd, **kwargs)

        with patch.object(gitcall.subprocess, "run", side_effect=recording):
            gitcall.git_out(self.repo, "merge-tree", "--write-tree", "HEAD", "HEAD")
        self.assertEqual([cmd[3:] for cmd, _ in calls][0], ["config", "--path", "--get", "core.attributesFile"])
        self.assertEqual({timeout for _, timeout in calls}, {gitcall.TOOL_CAP})
        with patch.object(gitcall.subprocess, "run",
                          side_effect=subprocess.TimeoutExpired("git", gitcall.TOOL_CAP)), \
                self.assertRaises(gitcall.Stopped):
            gitcall.git_out(self.repo, "rebase", "main")


if __name__ == "__main__":
    unittest.main(verbosity=2)
