"""A run's count settings are checked when it is launched, and a value that is no count refuses it.

`max_runs` in config.toml, or `AK_MAX_RUNS` in the environment over it, is how many runs the
host takes at once, and `run_memory_max_mb` one run's memory cap.  A value that is not a count
(a negative number, a string, a float, a boolean) must never be read as no cap: the launch exits
2 naming the file and the key, and a bad run count refuses it before the run's record is
written, in the foreground and with `--bg` alike.  Black-box: the program `AK_BIN` names runs
`ak run` from outside through tests/fixtures/akbin.py, on a config from akconfig.py and a
scratch task from taskfile.py; this test fails against `/bin/false`.
"""

import socket
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures import akconfig, taskfile

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
LAUNCHES = ((), ("--bg",))
ENV_REFUSED = "ak run: AK_MAX_RUNS must be a non-negative integer (0 disables the cap for tests)\n"


def offline(home):
    """A launch may ask the public model boards over HTTP itself, not through a tool on PATH:
    every proxy an HTTP client honours names a loopback port nobody listens on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{port}"))


class CountSettings(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        offline(self.home)
        self.config = self.home.path / ".agentkit" / "config.toml"
        self.task = taskfile.write(self.home, "none", done_when=("true",))

    def launch(self, *flags, settings=None, env=None):
        akconfig.write(self.home, ["opus"], settings=settings)
        return self.home.ak("run", str(self.task), *flags, env=env, timeout=60)

    def records(self):
        return [run / "run.json" for run in taskfile.runs(self.home)
                if (run / "run.json").is_file()]

    def test_a_max_runs_that_is_no_count_refuses_the_launch_before_its_record(self):
        for value in (-1, "3", 1.5, True):
            for flags in LAUNCHES:
                with self.subTest(value=value, flags=flags):
                    done = self.launch(*flags, settings={"max_runs": value},
                                       env={"AK_MAX_RUNS": None})
                    self.assertEqual(done.code, 2, done.out)
                    self.assertEqual(done.err, f"ak run: {self.config}: max_runs must be a "
                                               "non-negative integer\n")
                    self.assertEqual(self.records(), [])

    def test_an_ak_max_runs_that_is_no_count_refuses_the_launch_before_its_record(self):
        for value in ("abc", "-1", ""):
            for flags in LAUNCHES:
                with self.subTest(value=value, flags=flags):
                    done = self.launch(*flags, env={"AK_MAX_RUNS": value})
                    self.assertEqual(done.code, 2, done.out)
                    self.assertEqual(done.err, ENV_REFUSED)
                    self.assertEqual(self.records(), [])

    def test_ak_max_runs_stands_in_for_the_config_setting(self):
        # The Home's AK_MAX_RUNS=0 is a good count: the bad max_runs is never read, the
        # launch is admitted and writes its record, and goes on to fail for want of a harness.
        done = self.launch(settings={"max_runs": -1})
        self.assertNotIn("must be a non-negative integer", done.err)
        self.assertEqual(len(self.records()), 1, done.err)

    def test_a_run_memory_cap_that_is_not_positive_refuses_the_launch(self):
        for value in (0, -5, "512"):
            with self.subTest(value=value):
                done = self.launch(settings={"run_memory_max_mb": value})
                self.assertEqual(done.code, 2, done.out)
                self.assertTrue(done.err.startswith("ak run: "), done.err)
                self.assertTrue(done.err.endswith(f"{self.config}: run_memory_max_mb must be a "
                                                  "positive integer\n"), done.err)
                self.assertEqual(done.err.count("\n"), 1, done.err)


if __name__ == "__main__":
    unittest.main()
