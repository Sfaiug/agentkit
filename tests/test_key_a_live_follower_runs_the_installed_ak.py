"""A project's live follower runs the installed ak, as its lander does, whatever version the run
whose merge starts it was launched on.

On 14 Nov 2026 a fix to the follower was installed at 05:34, and the project's follower, started
39 minutes before by a run launched two days earlier, went on running that run's version.
Black-box: AK_BIN on the Home, project, seat and merge of
`test_key_merges_going_live_share_one_follower`, the Home holding the install and wrapper of
`test_key_the_lander_runs_the_installed_ak`, here recording the commit of each `watch --live`
start.  A run launched on the version before the installed one merges, and the follower that
takes it live is the installed version's.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_merges_going_live_share_one_follower import FollowedMerges
from test_key_the_lander_runs_the_installed_ak import starts, versions


class ALiveFollowerRunsTheInstalledAk(FollowedMerges):
    def test_a_run_on_an_older_version_hands_its_merge_to_the_installed_follower(self):
        install, old = versions(self.home, "watch", "--live")
        directory = self.merge("api", "one", ak_checkout=str(old))
        self.home.write("live-ok", "")
        self.until(lambda: json.loads((directory / "run.json").read_text()).get("live_at"),
                   "took the run live")
        self.assertEqual(set(starts(self.home)), {install.head()})


if __name__ == "__main__":
    unittest.main()
