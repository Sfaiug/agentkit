"""A seat filed by hand stays under that project; a seat nobody filed follows its runs' vote.

Offline, with invented checkouts and seat records under a temporary HOME.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import config, orch, run


class SeatProjectFiled(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {config.SESSION_ENV: "fix-api"}))
        self.acme = self.checkout(config.CODE / "acme")
        self.bramble = self.checkout(config.CODE / "bramble", worktree=True)
        self.record = config.save_session(self.cfg, "fix-api", "fable", ["opus"],
                                          {"cwd": str(config.CODE), "repo": None})

    def checkout(self, path, worktree=False):
        path.mkdir(parents=True)
        if worktree:
            (path / ".git").write_text("gitdir: ../fixture\n")
        else:
            (path / ".git").mkdir()
        return path

    def file(self, *args):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.main(["project", *args]), 0)
        self.assertIn("filed fix-api under ", out.getvalue())
        return config.load_session(self.cfg, "fix-api")

    def vote(self, name, project):
        directory = config.RUNS / name
        directory.mkdir()
        run.save_state(directory, {"run_id": name, "launched_session": "fix-api",
                                   "state": "queued", "project": str(project)})

    def test_file_current_or_named_seat_by_name_or_path(self):
        for seat in ((), ("fix-api",)):
            for checkout in (self.acme, self.bramble):
                for value in (checkout.name, str(checkout)):
                    with self.subTest(seat=seat, checkout=value):
                        record = self.file(*seat, value)
                        self.assertEqual(record, {**self.record, "repo": str(checkout), "filed": True})

    def test_checkout_name_matches_in_any_case(self):
        checkout = self.checkout(config.CODE / "CLOVER")
        for seat in ((), ("fix-api",)):
            for value in ("clover", "ClOvEr"):
                with self.subTest(seat=seat, checkout=value):
                    self.assertEqual(self.file(*seat, value)["repo"], str(checkout))

    def test_exact_name_wins_and_ambiguous_case_is_refused(self):
        upper = self.checkout(config.CODE / "ACME")
        for seat in ((), ("fix-api",)):
            for checkout in (self.acme, upper):
                with self.subTest(seat=seat, checkout=checkout.name):
                    self.assertEqual(self.file(*seat, checkout.name)["repo"], str(checkout))
            before = config.session_path("fix-api").read_bytes()
            for value in ("Acme", "aCmE"):
                with self.subTest(seat=seat, checkout=value):
                    with self.assertRaisesRegex(config.Error, "ambiguous checkout") as error:
                        orch.main(["project", *seat, value])
                    for checkout in (self.acme, upper):
                        self.assertIn(str(checkout), str(error.exception))
                    self.assertEqual(config.session_path("fix-api").read_bytes(), before)

    def test_home_path_and_agentkits_own_checkout(self):
        own = self.checkout(Path.home() / "agentkit")
        self.assertEqual(self.file("~/code/acme")["repo"], str(self.acme))
        for value in ("agentkit", str(own)):
            with self.subTest(checkout=value):
                self.assertEqual(self.file(value)["repo"], str(own))

    def test_old_seat_name_follows_a_rename(self):
        config.session_path("old-api").write_text('{"renamed": "fix-api"}\n')
        with patch.dict(os.environ, {config.SESSION_ENV: "old-api"}):
            self.assertEqual(self.file("acme")["repo"], str(self.acme))
        self.assertEqual(self.file("old-api", "bramble")["repo"], str(self.bramble))

    def test_non_checkout_is_refused_with_the_choices(self):
        scratch = self.checkout(self.root / "scratch")
        nested = self.acme / "src"
        nested.mkdir()
        plain = config.CODE / "notes"
        plain.mkdir()
        before = config.session_path("fix-api").read_bytes()
        for value in ("missing", str(scratch), str(nested), str(plain), "--bogus"):
            with self.subTest(checkout=value), self.assertRaises(config.Error) as error:
                orch.main(["project", value])
            self.assertIn("not a checkout", str(error.exception))
            for checkout in orch.checkouts():
                self.assertIn(str(checkout), str(error.exception))
            self.assertEqual(config.session_path("fix-api").read_bytes(), before)

    def test_missing_seat_and_wrong_argument_counts_are_refused(self):
        with patch.dict(os.environ, {config.SESSION_ENV: ""}):
            with self.assertRaisesRegex(config.Error, "use ak orch project <seat> <checkout>"):
                orch.main(["project", "acme"])
            self.file("fix-api", "acme")
        with self.assertRaisesRegex(config.Error, "no orchestrator session 'missing'"):
            orch.main(["project", "missing", "acme"])
        self.assertFalse(config.session_path("missing").exists())
        for args in ([], ["fix-api", "acme", "extra"]):
            with self.subTest(args=args), self.assertRaisesRegex(config.Error, "usage:"):
                orch.main(["project", *args])

    def test_filed_seat_stays_whatever_its_runs_vote(self):
        self.file("bramble")
        for name in ("first", "second", "third"):
            self.vote(name, self.acme)
            self.assertEqual(run.join_session_project("fix-api"), str(self.bramble))
        self.assertEqual(config.load_session(self.cfg, "fix-api")["repo"], str(self.bramble))
        self.assertEqual(self.file("acme")["repo"], str(self.acme))
        for name in ("fourth", "fifth", "sixth", "seventh"):
            self.vote(name, self.bramble)
        self.assertEqual(run.join_session_project("fix-api"), str(self.acme))
        self.assertEqual(config.load_session(self.cfg, "fix-api")["repo"], str(self.acme))

    def test_unfiled_seat_follows_its_runs_and_a_tie_keeps_its_project(self):
        self.vote("first", self.bramble)
        self.assertEqual(run.join_session_project("fix-api"), str(self.bramble))
        self.vote("second", self.acme)
        self.assertEqual(run.join_session_project("fix-api"), str(self.bramble))
        self.assertEqual(config.load_session(self.cfg, "fix-api")["repo"], str(self.bramble))
        self.vote("third", self.acme)
        self.assertEqual(run.join_session_project("fix-api"), str(self.acme))
        self.assertEqual(config.load_session(self.cfg, "fix-api")["repo"], str(self.acme))

if __name__ == "__main__":
    unittest.main(verbosity=2)
