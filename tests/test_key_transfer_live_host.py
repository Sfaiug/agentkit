"""Inside a seat, scp, rsync and sftp may not write onto the live host; everything else runs.

A file reaches the live host only through the repo, so a seat's hand-made copy onto it is refused
and says why, and the real tool never runs.  A read from the live host, a copy to any other host,
and every transfer once the owner has named no live host (`live_host` in config.toml) run the real
tool as typed, with its output and exit code.  Black-box: the shims a seat's launch installs
(tests/fixtures/shims.py), run as a seat's commands with a logging fake as the real tool, judged by
the exit code, what was printed and the fake's calls; this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.shims import Shims

REFUSED = ("ak refused `{}` to prod: a file reaches the live host only through the repo. Commit "
           "the change and let it deploy; a seat writes nothing onto prod by hand.\n")
TOOLS = ("scp", "rsync", "sftp")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LiveHost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.shims = Shims(cls.home)
        Seat(cls.home, "acme", alive=False)
        for tool in TOOLS:
            cls.shims.fake(tool, out=f"{tool} ran\n")
        cls.config = cls.home.path / ".agentkit" / "config.toml"
        cls.shipped = cls.config.read_text()
        cls.live = f'live_host = "prod"\n{cls.shipped}'
        cls.config.write_text(cls.live)

    def ran(self, *argv):
        """The call ran the real tool with its argv as typed, and its output came back."""
        tool, args = argv[0], list(argv[1:])
        done = self.shims.run(*argv)
        self.assertEqual((done.code, done.out, done.err), (0, f"{tool} ran\n", ""))
        self.assertEqual(self.home.calls(tool)[-1], args)

    def test_a_seat_writing_onto_the_live_host_is_refused_and_nothing_runs(self):
        cases = [("scp", "a.txt", "prod:/srv/"),
                 ("scp", "-r", "x", "deploy@prod:/srv/x"),
                 ("scp", "a.txt", "scp://prod/srv/a.txt"),
                 ("rsync", "-a", "x/", "prod:/srv/x/"),
                 # an option after the target hides no write
                 ("rsync", "-a", "x/", "prod:/srv/x/", "--exclude", "tmp"),
                 ("sftp", "prod"),
                 ("sftp", "deploy@prod")]
        for argv in cases:
            with self.subTest(argv=argv):
                before = len(self.home.calls(argv[0]))
                done = self.shims.run(*argv)
                self.assertEqual((done.code, done.out, done.err),
                                 (1, "", REFUSED.format(argv[0])))
                self.assertEqual(len(self.home.calls(argv[0])), before)

    def test_a_read_from_the_live_host_and_a_copy_elsewhere_run_as_typed(self):
        for argv in (("scp", "prod:/srv/a.txt", "."),
                     ("rsync", "-a", "prod:/srv/x/", "x/"),
                     ("scp", "a.txt", "other:/srv/"),
                     ("rsync", "-a", "x/", "other:/srv/x/"),
                     # a local file that only shares the host's name
                     ("scp", "a.txt", "prod"),
                     ("sftp", "other")):
            with self.subTest(argv=argv):
                self.ran(*argv)

    def test_with_no_live_host_named_a_seat_may_copy_anywhere(self):
        self.addCleanup(self.config.write_text, self.live)
        for config in (self.shipped, None):
            with self.subTest(config="shipped" if config else "none"):
                if config:
                    self.config.write_text(config)
                else:
                    self.config.unlink()
                for argv in (("scp", "a.txt", "prod:/srv/"),
                             ("rsync", "-a", "x/", "prod:/srv/x/"),
                             ("sftp", "prod")):
                    with self.subTest(argv=argv):
                        self.ran(*argv)

    def test_the_real_tools_failure_comes_back_as_its_own(self):
        self.addCleanup(self.shims.fake, "rsync", out="rsync ran\n")
        self.shims.fake("rsync", code=23, out="rsync: some files were not transferred\n")
        done = self.shims.run("rsync", "-a", "prod:/srv/x/", "x/")
        self.assertEqual((done.code, done.out), (23, "rsync: some files were not transferred\n"))
        self.assertEqual(self.home.calls("rsync")[-1], ["-a", "prod:/srv/x/", "x/"])


if __name__ == "__main__":
    unittest.main()
