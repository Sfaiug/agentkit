"""A client's owed install with no keep link still puts back a program that cannot start.

Before clients kept the version a move replaced (`versions.keep_link`), a client's move whose
install.sh failed left no link, and the retry, finding none, cleared the owed install with a
program live that could not start.  The retry finds the version replaced where the move's swap
left it, and puts the move back as any client's.  Offline, on tests/test_go_live_retries_install.py's
fixture: the move is this code's, its link removed as a move before left none.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_go_live_retries_install as retries
from agentkit import config, gc, update, versions


class AClientMoveLeftUnlinkedIsPutBack(unittest.TestCase):
    setUp = retries.GoLiveRetriesInstall.setUp

    def commit(self, ak, message):
        seed = self.root / "seed"
        (seed / "bin").mkdir(exist_ok=True)
        (seed / "bin" / "ak").write_text(ak)
        (seed / "bin" / "ak").chmod(0o755)
        retries.git(seed, "add", "-A")
        retries.git(seed, "commit", "-q", "-m", message)
        retries.git(seed, "push", "-q", "origin", "main")
        return retries.git(seed, "rev-parse", "HEAD")

    def test_a_retry_puts_back_a_program_that_cannot_start(self):
        before = self.commit("#!/bin/sh\nexit 0\n", "starts")
        retries.git(self.clone, "fetch", "-q", "origin")
        retries.git(self.clone, "merge", "-q", "--ff-only", before)
        after = self.commit('#!/bin/sh\n[ "$1" != --help ] || exit 1\n', "cannot start")
        (config.STATE / "server").write_text("acme-home\n")
        (self.root / "broken").touch()
        with patch.dict(os.environ, {"AK_NOTIFY_SINK": "dry-run", "AK_RUN_DEPTH": "0"}), \
                patch.object(gc, "tmp_processes", return_value=(set(), {})), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(update.update_agentkit(), 3)
            self.assertEqual(retries.git(self.clone, "rev-parse", "HEAD"), after)
            versions.keep_link().unlink()
            (self.root / "broken").unlink()
            code = update.update_agentkit(pull=False)
        self.assertEqual((code, retries.git(self.clone, "rev-parse", "HEAD")), (1, before))
        self.assertFalse((config.STATE / update.PENDING).exists())


if __name__ == "__main__":
    unittest.main()
