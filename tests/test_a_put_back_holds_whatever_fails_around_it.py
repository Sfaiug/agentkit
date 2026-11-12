"""A move put back (agentkit/back.py) stays put back, and is heard of, whatever fails around it.

A tick that chose its move before the put back looks at it again under the move lock, and goes
nowhere near the commit put back.  A ref git refuses to write puts nothing back, and the next try
does.  A page the webhook refuses is retried by the watcher, as no caller asks for it again.  The
tick that made a move restarts the keeper's hour at its end even when its state cannot be saved.

The Home is tests/test_go_live_retries_install.py's: an offline origin and its clone at
~/agentkit, one commit behind.
"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_go_live_retries_install as retries
from fixtures.clock import Clock
from fixtures.sink import Sink
from agentkit import back, config, notify, update, versions, watch

QUIET = {"AK_NOTIFY_SINK": "dry-run", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_RUN_LOG": "",
         "AK_PARENT_RUN": "", "AGENTKIT_SESSION": ""}


class APutBackHoldsWhateverFailsAroundIt(unittest.TestCase):
    setUp = retries.GoLiveRetriesInstall.setUp

    def head(self):
        return retries.git(self.clone, "rev-parse", "HEAD")

    def move(self, **kw):
        with patch.dict(os.environ, QUIET), redirect_stdout(io.StringIO()):
            return update.update_agentkit(**kw)

    def moved(self):
        """~/agentkit moved to the commit ahead, and the commit it was at."""
        before = self.head()
        self.assertEqual(self.move(), 0)
        self.assertEqual((self.head(), versions.keep_link().is_symlink()), (self.new, True))
        return before

    def test_a_move_chosen_before_the_put_back_goes_nowhere(self):
        before = self.moved()
        with patch.dict(os.environ, QUIET):
            self.assertEqual(back.main([]), 0)
        self.assertEqual(self.move(pull=self.new), 0)
        self.assertEqual(self.head(), before)

    def test_a_ref_git_refuses_puts_nothing_back_until_it_is_written(self):
        before = self.moved()
        common = Path(self.clone, retries.git(self.clone, "rev-parse", "--git-common-dir"))
        lock = common / "refs" / "release" / "failed" / f"{self.new}.lock"
        lock.parent.mkdir(parents=True)
        lock.touch()
        with patch.dict(os.environ, QUIET):
            self.assertEqual(back.main([]), 1)
            self.assertEqual((self.head(), versions.keep_link().is_symlink()), (self.new, True))
            lock.unlink()
            self.assertEqual(back.main([]), 0)
        self.assertEqual(self.move(), 0)
        self.assertEqual(self.head(), before)

    def test_a_page_the_webhook_refuses_goes_out_later(self):
        self.moved()
        home = SimpleNamespace(env={})
        with Sink(home) as sink, patch.dict(os.environ, home.env):
            sink.script(503)
            self.assertEqual(back.main([]), 0)
            event, = notify.outbox().glob("*.json")
            due = json.loads(event.read_text())
            event.write_text(json.dumps({**due, "next_attempt": 0}))
            notify.retry_pending()
            notify.retry_pending()
            self.assertEqual([json.loads(event.read_text())[key] for key in ("status", "attempts")],
                             ["delivered", 2])

    def test_the_hour_starts_at_the_moving_ticks_end_though_its_state_is_not_saved(self):
        ended = time.time() + 40 * 60
        clock = Clock(time.sleep)
        clock.time = lambda: ended
        (config.STATE / "watch.tmp").mkdir()        # where the state is written whole first
        with patch.object(config, "BEGAN", os.stat(self.clone)), \
                patch.object(watch, "time", clock), \
                patch.object(watch, "local_passes", return_value=[("move", self.move, False)]), \
                patch.object(watch, "gh_json", return_value=(None, "offline")), \
                patch.dict(os.environ, QUIET), self.assertRaises(IsADirectoryError):
            watch.main([])
        self.assertEqual(self.head(), self.new)
        self.assertAlmostEqual(os.lstat(versions.keep_link()).st_mtime, ended, places=3)


if __name__ == "__main__":
    unittest.main()
