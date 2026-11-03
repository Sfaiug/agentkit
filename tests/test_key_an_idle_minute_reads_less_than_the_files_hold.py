"""An idle minute reads less than its seats and runs hold."""

import time
import unittest

from test_key_idle_screen_reads_only_what_changed import MINUTE, OpenScreen


class IdleScreenReadsOnlyWhatChanged(OpenScreen):
    def test_1_an_idle_minute_reads_less_than_the_files_hold(self):
        start = self.read()
        time.sleep(MINUTE)
        self.assertLess(self.read() - start, self.budget)


if __name__ == "__main__":
    unittest.main()
