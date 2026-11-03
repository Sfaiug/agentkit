"""The prompt's Mac wait is shared by every pasted word, under an injected clock."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import shlex
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config, macbridge


class PastedMacPaths(unittest.TestCase):
    def test_all_paths_share_ten_seconds_even_when_the_mac_never_answers(self):
        now, waits = 100, []

        def unanswered(path, timeout):
            nonlocal now
            waits.append((path, timeout))
            now += timeout
            raise config.Error("no answer from the Mac bridge")

        with patch.object(macbridge, "time", SimpleNamespace(monotonic=lambda: now)), \
                patch.object(macbridge, "fetch_one", side_effect=unanswered):
            news = macbridge.pasted_context("Read /Users/acme/a.pdf and /Users/acme/b.pdf")
        self.assertEqual(waits, [("/Users/acme/a.pdf", 10), ("/Users/acme/b.pdf", 0)])
        self.assertIn("ak fetch /Users/acme/a.pdf", news)
        self.assertIn("ak fetch /Users/acme/b.pdf", news)

    def test_a_word_is_fetched_once_without_reading_another_path_inside_it(self):
        path = "/Users/acme/copy/Users/acme/report.pdf"
        with patch.object(macbridge, "fetch_one", return_value="/tmp/report.pdf") as fetch:
            news = macbridge.pasted_context(f"Read {path} and {path}")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args[0], path)
        self.assertEqual(news, f"{path} is at /tmp/report.pdf")

    def test_a_failed_file_does_not_hide_another_file(self):
        with patch.object(macbridge, "fetch_one", side_effect=[
                config.Error("permission denied"), "/tmp/report.pdf"]):
            news = macbridge.pasted_context("Read /Users/acme/a.pdf and /Users/acme/b.pdf")
        self.assertIn("permission denied", news)
        self.assertIn("ak fetch /Users/acme/a.pdf", news)
        self.assertIn("/Users/acme/b.pdf is at /tmp/report.pdf", news)

    def test_retry_commands_preserve_the_original_shell_word(self):
        paths = [r"/Users/acme/literal\ space.pdf", r"/Users/acme/literal\(one).pdf",
                 r"/Users/acme/literal\\.pdf", "/Users/acme/owner's report.pdf",
                 "/Users/acme/trailing space.pdf "]
        for path in paths:
            with self.subTest(path=path):
                with patch.object(macbridge, "fetch_one", side_effect=config.Error("offline")):
                    news = macbridge.pasted_context("Read " + shlex.quote(path))
                command = news.split("try ", 1)[1].removesuffix(" later.")
                argv = shlex.split(command)
                self.assertEqual(argv[:2], ["ak", "fetch"])
                with patch.object(macbridge, "fetch_one", return_value="/tmp/report.pdf") as fetch, \
                        redirect_stdout(io.StringIO()):
                    self.assertEqual(macbridge.fetch_main(argv[2:]), 0)
                self.assertEqual(fetch.call_args.args[0], path)


if __name__ == "__main__":
    unittest.main()
