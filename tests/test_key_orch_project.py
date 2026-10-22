"""`ak orch project` files a seat under a checkout and says what else is in flight there.

A seat filed under a project is listed under it on the menu and plans its work around the other
seats on that checkout, so the verb must find the checkout a person or a model names -- by name in
any case, by path, or by a worktree of it -- refuse plainly what it cannot place, and name every
other seat's open plan lines and the files its going runs change.  Filing is never refused for a
run of the seat's own that is going.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, judged by its exit code, what it prints and the seat's record.
"""

from itertools import takewhile
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig


def written(outcome, place):
    """A plan line as `ak plan` writes it, its box aside: the checkout and root it was written
    on, which place it for a seat filed elsewhere."""
    return f"{outcome} · check: `python3 t.py` · {place} · written 2026-10-20 09:00"


def record(home, name):
    return json.loads((home.path / f".agentkit/state/session-{name}.json").read_text())


def plan(home, name, *lines):
    home.write(f".agentkit/state/plan-{name}.md", "# plan\n\n" + "".join(f"{line}\n"
                                                                      for line in lines))


def run(home, run_id, state, task_files=None):
    """A run's record, and the saved task whose `files:` a run with no worktree yet changes."""
    home.write(f".agentkit/runs/{run_id}/run.json", state)
    home.write(f".agentkit/runs/{run_id}/task.md",
               "---\n" + (f"files: {task_files}\n" if task_files else "") + "---\n# Work\n")


def root(rig):
    return rig.git("rev-list", "--max-parents=0", "HEAD")[:12]


class Filing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.code = home.path / "code"
        Rig(home, "acme", files={"README.md": "acme\n"})
        Rig(home, "Acme-Web", files={"README.md": "web\n"})
        for name in ("fix-api", "other", "tree", "new", "fresh", "shipped"):
            Seat(home, name, cwd=home.path, alive=False)
        home.write(".agentkit/state/session-old.json", {"renamed": "new"})

    def filed(self, *args, env=None):
        done = self.home.ak("orch", "project", *args, env=env)
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def test_the_seat_it_runs_in_is_filed_under_the_checkout_named(self):
        out = self.filed("acme", env={"AGENTKIT_SESSION": "fix-api"})
        self.assertEqual(out, "filed fix-api under acme\nnothing else in flight on acme\n")
        kept = record(self.home, "fix-api")
        self.assertEqual((kept["repo"], kept["filed"]), (str(self.code / "acme"), True))
        self.assertEqual(kept["orchestrator"], "opus")      # the rest of the record stays

    def test_a_checkout_is_named_in_any_case_or_by_its_path(self):
        for named, project in (("ACME-web", "Acme-Web"), (str(self.code / "acme"), "acme"),
                               ("~/code/Acme-Web", "Acme-Web")):
            with self.subTest(named):
                self.assertEqual(self.filed("other", named),
                                 f"filed other under {project}\n"
                                 f"nothing else in flight on {project}\n")
                self.assertEqual(record(self.home, "other")["repo"], str(self.code / project))

    def test_a_worktree_of_a_checkout_files_the_seat_under_that_checkout(self):
        added = self.home.path / ".agentkit/wt/acme-fix"
        done = self.home.run("git", "-C", str(self.code / "acme"), "worktree", "add", "-q",
                             "-b", "fix", str(added))
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.filed("tree", str(added)).splitlines()[0], "filed tree under acme")
        self.assertEqual(record(self.home, "tree")["repo"], str(self.code / "acme"))

    def test_a_renamed_seat_is_filed_under_the_name_it_goes_by_now(self):
        for args, env in ((("old", "acme"), None), (("Acme-Web",), {"AGENTKIT_SESSION": "old"})):
            with self.subTest(args=args):
                project = args[-1]
                self.assertEqual(self.filed(*args, env=env).splitlines()[0],
                                 f"filed new under {project}")
                self.assertEqual(record(self.home, "new")["repo"], str(self.code / project))
                self.assertEqual(record(self.home, "old"), {"renamed": "new"})

    def test_a_seat_beside_one_whose_plan_is_done_hears_nothing_else_is_in_flight(self):
        self.filed("shipped", "Acme-Web")
        plan(self.home, "shipped", "- [x] the parser is shipped")
        self.assertEqual(self.filed("fresh", "Acme-Web"),
                         "filed fresh under Acme-Web\nnothing else in flight on Acme-Web\n")


class InFlight(unittest.TestCase):
    """fix-api files itself under acme, where `other` and `quiet` are filed, `beta` filed under
    Acme-Web has going runs, and runs go that no seat launched."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        code = home.path / "code"
        acme = Rig(home, "acme", files={"README.md": "acme\n"})
        web = Rig(home, "Acme-Web", files={"README.md": "web\n"})
        for name, repo in (("fix-api", None), ("other", "acme"), ("quiet", "acme"),
                           ("beta", "Acme-Web"), ("long", "Acme-Web")):
            filed = {"repo": str(code / repo), "filed": True} if repo else {}
            Seat(home, name, cwd=home.path, alive=False, record=filed)
        cls.on_acme = written("api 404s", f"~/code/acme#{root(acme)}")
        plan(home, "other", f"- [ ] {written('parser ok', '~/code/acme#abc1234')}",
             "- [x] done line", "- [ ] a hand-kept line")
        plan(home, "beta", f"- [ ] {cls.on_acme}",
             f"- [ ] {written('on a commit acme lacks', '~/code/acme#abc1234')}",
             f"- [ ] {written('on the web', f'~/code/Acme-Web#{root(web)}')}")
        cls.long = " ".join(f"step{i} of the long outcome" for i in range(12))
        plan(home, "long", f"- [ ] {cls.long}")
        repo = {"repo": str(code / "acme")}
        # beta's running run changes cli.py in a commit and README.md in its worktree
        tree = home.path / ".agentkit/wt/acme-beta"
        acme.git("worktree", "add", "-q", "-b", "beta-cli", str(tree))
        (tree / "cli.py").write_text("print()\n")
        acme.git("-C", str(tree), "add", "cli.py")
        acme.git("-C", str(tree), "commit", "-q", "-m", "cli")
        (tree / "README.md").write_text("changed\n")
        run(home, "20261020-0900-aaaa", {"state": "running", **repo, "launched_session": "beta",
                                         "worktree": str(tree), "base_sha": acme.head()})
        run(home, "20261020-0901-bbbb", {"state": "queued", **repo, "launched_session": "beta"},
            "api.py, docs/api.md")
        run(home, "20261020-0902-cccc", {"state": "queued", "repo": str(code / "Acme-Web"),
                                         "launched_session": "beta"}, "web.py")
        run(home, "20261020-0903-dddd", {"state": "stopped", **repo, "launched_session": "other",
                                         "lease_wait": {"run": "20261020-0901-bbbb"}}, "parser.py")
        run(home, "20261020-0904-eeee", {"state": "pass", **repo, "launched_session": "quiet"},
            "gone.py")
        run(home, "20261020-0905-ffff", {"state": "queued", **repo}, "setup.py")
        run(home, "20261020-0906-gggg", {"state": "queued", **repo})
        run(home, "20261020-0907-hhhh", {"state": "queued", **repo, "launched_session": "fix-api"},
            "own.py")

    def project(self, checkout, columns=None):
        env = {"AGENTKIT_SESSION": "fix-api", **({"COLUMNS": str(columns)} if columns else {})}
        done = self.home.ak("orch", "project", checkout, env=env)
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def test_other_seats_open_lines_and_what_their_going_runs_change_are_listed(self):
        # beta, filed elsewhere, shows only its line written on acme; other's parked run counts;
        # quiet, with nothing open or going, is left out, as are a run with no files and
        # fix-api's own run, which does not stop it being filed
        self.assertEqual(self.project("acme"), (
            "filed fix-api under acme\n"
            "in flight on acme, plan around it:\n"
            "  beta\n"
            f"    plan: {self.on_acme}\n"
            "    changing: README.md, api.py, cli.py, docs/api.md\n"
            "  other\n"
            f"    plan: {written('parser ok', '~/code/acme#abc1234')}\n"
            "    plan: a hand-kept line\n"
            "    changing: parser.py\n"
            "  run 20261020-0905-ffff\n"
            "    changing: setup.py\n"))
        self.assertEqual(record(self.home, "fix-api")["repo"], str(self.home.path / "code/acme"))

    def test_a_long_plan_line_wraps_at_the_terminal_width_and_never_past_120_columns(self):
        for columns, cap in ((60, 60), (250, 120)):
            with self.subTest(columns=columns):
                lines = self.project("Acme-Web", columns).splitlines()
                self.assertLessEqual(max(map(len, lines)), cap)
                after = lines[lines.index("  long") + 1:]
                parts = list(takewhile(lambda line: line.startswith("    "), after))
                self.assertEqual(" ".join(part.strip() for part in parts), f"plan: {self.long}")
                self.assertGreater(len(parts), 1)
                if columns == 250:
                    self.assertGreater(len(parts[0]), 100)


class Refusals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.code = home.path / "code"
        for name in ("acme", "Acme-Web", "ACME-WEB"):
            Rig(home, name, files={"README.md": f"{name}\n"})
        (cls.code / "notes").mkdir()
        elsewhere = home.path / "elsewhere/acme"
        elsewhere.mkdir(parents=True)
        assert home.run("git", "init", "-q", str(elsewhere)).code == 0
        for name in ("other", "beta"):
            Seat(home, name, cwd=home.path, alive=False)

    def refused(self, *args, env=None):
        done = self.home.ak("orch", "project", *args, env=env)
        self.assertEqual(done.code, 2, done.out)
        self.assertEqual(done.out, "")
        return done.err

    def test_what_names_no_checkout_is_refused_with_the_checkouts_there_are(self):
        known = ", ".join(str(self.code / name) for name in ("ACME-WEB", "Acme-Web", "acme"))
        for named in ("nothere", "notes", "~/elsewhere/acme",
                      str(self.home.path / "elsewhere/acme")):
            with self.subTest(named):
                self.assertEqual(self.refused("other", named),
                                 f"ak orch: not a checkout: '{named}' (checkouts: {known})\n")
        self.assertNotIn("repo", record(self.home, "other"))

    def test_with_no_checkouts_at_all_the_refusal_says_none(self):
        with Home() as home:
            Seat(home, "other", cwd=home.path, alive=False)
            done = home.ak("orch", "project", "other", "acme")
            self.assertEqual((done.code, done.err),
                             (2, "ak orch: not a checkout: 'acme' (checkouts: none)\n"))

    def test_a_name_two_checkouts_share_but_for_case_is_ambiguous(self):
        both = ", ".join(str(self.code / name) for name in ("ACME-WEB", "Acme-Web"))
        self.assertEqual(self.refused("other", "acme-web"),
                         f"ak orch: ambiguous checkout: 'acme-web' (checkouts: {both})\n")
        self.assertNotIn("repo", record(self.home, "other"))

    def test_a_name_spelled_exactly_wins_over_one_that_differs_only_in_case(self):
        done = self.home.ak("orch", "project", "beta", "Acme-Web")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(done.out.splitlines()[0], "filed beta under Acme-Web")
        self.assertEqual(record(self.home, "beta")["repo"], str(self.code / "Acme-Web"))

    def test_the_one_argument_form_outside_a_seat_is_refused(self):
        self.assertEqual(self.refused("acme"),
                         "ak orch: ak orch project <checkout> files the session it runs in, and "
                         "this is not one; use ak orch project <seat> <checkout>\n")

    def test_a_seat_with_no_record_is_refused_and_given_none(self):
        for args, env in ((("ghost", "acme"), None), (("acme",), {"AGENTKIT_SESSION": "ghost"})):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*args, env=env),
                                 "ak orch: no orchestrator session 'ghost'\n")
        self.assertFalse((self.home.path / ".agentkit/state/session-ghost.json").exists())

    def test_no_arguments_or_too_many_print_the_usage(self):
        for args in ((), ("other", "acme", "extra")):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*args),
                                 "ak orch: usage: ak orch project [<seat>] <checkout>\n")


if __name__ == "__main__":
    unittest.main()
