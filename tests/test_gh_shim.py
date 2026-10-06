"""The gh guard: a seat's `gh` shim refuses `gh pr merge` (merging is ak's job), and runs the real
gh otherwise. The one seat that may merge by hand is the inbox, which `ak watch` asks first.

Offline: the shim is `gh` first on PATH; a fake real gh sits behind it and only logs its argv. No
GitHub is reached. ak's own merges run seatless, so the shim never engages for them -- the
seatless case below stands in for that.
"""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "tools/gh-shim"
# The fake real gh: it only records its argv, so the test can tell a refusal from a pass-through.
REAL = "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"$RAN_LOG\"\nexit 0\n"
# A seat running any of these is refused: merging is ak's job once a PR passes with green checks.
REFUSED = (["pr", "merge", "123"],
           ["pr", "merge", "https://github.com/acme/fix-api/pull/7", "--squash", "--delete-branch"],
           ["pr", "merge", "--rebase", "fix-api"],
           ["pr", "merge", "--match-head-commit", "abc123", "7"],
           ["pr", "-R", "acme/fix-api", "merge", "7"],       # -R takes a value before the subcommand
           ["pr", "--repo", "acme/fix-api", "merge", "7"],
           ["pr", "--repo=acme/fix-api", "merge", "7"])
# Every other gh call runs the real gh, as does the inbox's merge and a worker's.
ALLOWED = (["pr", "view", "7"],
           ["pr", "list"],
           ["pr", "create", "--fill"],
           ["pr", "checkout", "7"],
           ["api", "repos/acme/fix-api/pulls/7"],
           ["api", "-X", "PUT", "repos/acme/fix-api/pulls/7/merge"],   # the API merge is out of reach, by design
           ["repo", "view"],
           ["--version"])


class GhShim(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / ".agentkit/state").mkdir(parents=True)
        for s in ("mine", "inbox"):
            (self.home / f".agentkit/state/session-{s}.json").write_text("{}\n")
        self.shimdir = self.home / "shim"
        self.realdir = self.home / "real"
        self.shimdir.mkdir()
        self.realdir.mkdir()
        (self.shimdir / "gh").symlink_to(SHIM)          # the shim is `gh`, first on PATH
        real = self.realdir / "gh"
        real.write_text(REAL)
        real.chmod(0o755)
        self.ran = self.home / "ran.log"
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("AK_RUN_ROLE", "AGENTKIT_SESSION", "AGENTKIT_INBOX_SESSION")}
        self.env.update(HOME=str(self.home), AGENTKIT_SESSION="mine", RAN_LOG=str(self.ran),
                        PATH=f"{self.shimdir}{os.pathsep}{self.realdir}{os.pathsep}{os.environ.get('PATH', '')}")

    def run_gh(self, args, **env):
        self.ran.write_text("")
        result = subprocess.run([str(self.shimdir / "gh"), *args], capture_output=True,
                                text=True, timeout=30, env={**self.env, **env})
        ran = self.ran.read_text() if self.ran.exists() else ""
        return result, ran

    def test_a_seats_pr_merge_is_refused(self):
        for args in REFUSED:
            with self.subTest(args=args):
                result, ran = self.run_gh(args)
                self.assertEqual(result.returncode, 1, (args, result.stderr))
                self.assertIn("ak refused `gh pr merge`", result.stderr)
                self.assertNotIn("merge", ran)          # the real gh never ran the merge

    def test_other_gh_calls_run_the_real_gh(self):
        for args in ALLOWED:
            with self.subTest(args=args):
                result, ran = self.run_gh(args)
                self.assertEqual(result.returncode, 0, (args, result.stderr))
                self.assertTrue(ran.strip(), (args, "reached no real gh"))

    def test_the_inbox_may_merge(self):
        result, ran = self.run_gh(REFUSED[0], AGENTKIT_SESSION="inbox")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("merge", ran)                     # it reached the real gh

    def test_a_renamed_inbox_may_merge(self):
        (self.home / ".agentkit/state/session-mailbox.json").write_text("{}\n")
        result, ran = self.run_gh(REFUSED[0], AGENTKIT_SESSION="mailbox",
                                  AGENTKIT_INBOX_SESSION="mailbox")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("merge", ran)

    def test_a_worker_and_a_seatless_shell_run_the_real_gh(self):
        for env in ({"AK_RUN_ROLE": "worker"}, {"AGENTKIT_SESSION": ""}):
            with self.subTest(env=env):
                result, ran = self.run_gh(REFUSED[0], **env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("merge", ran)

    def test_a_guard_that_cannot_import_runs_the_real_gh(self):
        # a live checkout mid-update or a pre-3.11 python without tomllib must not cost a seat its gh
        broken = self.home / "py"
        broken.mkdir()
        (broken / "tomllib.py").write_text('raise ImportError("no tomllib")\n')
        result, ran = self.run_gh(REFUSED[0], PYTHONPATH=str(broken))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("merge", ran)

    def test_the_real_gh_is_the_first_after_the_shims_own_dir(self):
        # a wrapper ahead of the shim that calls through to it is never chosen, or it would loop;
        # one between the shim and the real gh is chosen, so it chains
        base = self.home / "chain"
        ahead, wrap = base / "ahead", base / "wrap"
        for d, body in ((ahead, f'exec "{self.shimdir / "gh"}" "$@"'), (wrap, "")):
            d.mkdir(parents=True)
            (d / "gh").write_text(f'#!/bin/sh\necho {d.name} >> "$RAN_LOG"\n{body}\n')
            (d / "gh").chmod(0o755)
        path = os.environ.get("PATH", "")
        result, ran = self.run_gh(["pr", "view", "7"], AGENTKIT_SESSION="",
                                  PATH=os.pathsep.join(map(str, (self.shimdir, wrap, self.realdir, path))))
        self.assertEqual((result.returncode, ran), (0, "wrap\n"))
        self.ran.write_text("")
        result = subprocess.run([str(ahead / "gh"), "pr", "view", "7"], capture_output=True, text=True,
                                timeout=30, env={**self.env, "AGENTKIT_SESSION": "",
                                                 "PATH": os.pathsep.join(map(str, (ahead, self.shimdir,
                                                                                  self.realdir, path)))})
        self.assertEqual((result.returncode, self.ran.read_text()), (0, "ahead\npr view 7\n"))

    def test_ak_s_own_gh_runs_seatless(self):
        # ak's git and gh go through run.tool_env, which drops the seat's name, so the gh shim
        # (which engages only on a seat's name) never reaches ak's own do_merge / ak run merge
        import sys as _sys
        from unittest import mock
        _sys.path.insert(0, str(REPO))
        from agentkit import config, run
        with mock.patch.dict(os.environ, {config.SESSION_ENV: "mine"}):
            self.assertNotIn(config.SESSION_ENV, run.tool_env())


if __name__ == "__main__":
    unittest.main()
