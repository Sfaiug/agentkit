"""A suite helper that is a Linux machine with docker runs a suite's pieces as the Mac does.

Its pieces passing there take no turn here; a piece failing there runs again here, and that run
decides.  Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py; ssh runs what it is given on `acme-linux`, the Linux machine of
tests/fixtures/akmachine.py.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine
from fixtures.akline import Line


class HelperOnLinux(unittest.TestCase):
    def land(self, b):
        """What the lander left its one member waiting on, its suite's runs here and its runs
        on the machine, where `t/b.sh`, in piece 2/2, is `b`."""
        line = Line({"t/a.sh": "true\n", "t/b.sh": b,
                     "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        self.addCleanup(line.close)
        akconfig.write(line.home, ["opus", "astra"], settings={"suite_helper": "acme-linux"})
        machine = akmachine.install(line.home)
        line.member({"api.txt": "x\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.said = "".join(path.read_text(errors="replace")
                            for path in (line.home.path / ".agentkit").rglob("*.log"))
        there = sorted(tuple(run.split(" ", 2))
                       for log in machine.glob("docker/roots/*/home/ak/work/.git/suite.log")
                       for run in log.read_text().splitlines())
        return line.verdict(1), line.runs(), there

    def test_pieces_passing_there_take_no_turn_here(self):
        verdict, runs, there = self.land("true\n")
        self.assertIn("land", verdict, verdict)
        self.assertEqual((runs, there), ([], [("piece", "1/2", ""), ("piece", "2/2", "")]))

    def test_a_piece_failing_only_there_passes_here_and_lands(self):
        verdict, runs, _ = self.land('[ "$container" != docker ]\n')
        self.assertIn("land", verdict, verdict)
        self.assertEqual(runs, [("alone", ""), ("piece", "2/2", "")])
        self.assertIn("failed on the suite helper acme-linux, then passed on its re-run",
                      self.said)

    def test_a_piece_failing_there_and_here_keeps_the_member_red(self):
        verdict, runs, _ = self.land("! test -f api.txt\n")    # red on the member's tree alone
        self.assertIn("fix", verdict, verdict)
        self.assertEqual(runs[0], ("alone", ""))


if __name__ == "__main__":
    unittest.main()
