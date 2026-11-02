"""A tick's log reads the same however its text was cut into writes: each line starts with its
date and time, and a CR and its LF written apart stay one line end, as `print` writes them.

In-process: gh's output, the CRLF a tick would meet, reaches it with its line ends already LF.
"""

import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import watch


def logged(*writes):
    log = io.StringIO()
    stream = watch.Stamped(log)
    with patch.object(watch.time, "strftime", return_value="T "):
        for text in writes:
            stream.write(text)
    return log.getvalue()


class LineEnds(unittest.TestCase):
    def test_every_cut_of_a_text_logs_each_of_its_lines_once_stamped(self):
        text = "a\r\n\r\n\n\rb\rc\nd\x0ce \r\r\nf"
        lines = text.splitlines(keepends=True)
        self.assertIn("\r", lines)      # a CR no LF follows still ends its line
        expected = "".join("T " + line for line in lines)
        for cut in range(len(text) + 1):
            with self.subTest(first=text[:cut]):
                self.assertEqual(logged(text[:cut], text[cut:]), expected)


if __name__ == "__main__":
    unittest.main()
