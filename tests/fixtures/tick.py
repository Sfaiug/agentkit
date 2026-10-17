"""A test's tick: `watch.main` runs only the passes a test names, under no login of the caller's.

A pass is named by its WARN line in `watch.local_passes`.  Every other pass of that table is a
no-op, one added to it later included: a test listing the passes to stub would run a new one for
real, and the weekly audit pass opened a real seat that way.  HOME is the test's temporary
directory, and no harness's state or login variable of the caller's (`config.state_env_names()`,
CLAUDE_CONFIG_DIR among them) is left for a pass to find its way back to the owner's login with.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import sys
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from agentkit import config, watch


@contextmanager
def only_passes(home, *named):
    """Every pass the tick reached, named or not, in its order."""
    table, reached = watch.local_passes, []

    def passes(state, dry_run, log):
        for what, step, also_dry in table(state, dry_run, log):
            def reach(what=what, step=step):
                reached.append(what)
                if what in named:
                    step()
            yield what, reach, also_dry

    with patch.object(watch, "local_passes", passes), \
            patch.dict(os.environ, {"HOME": str(home)}):
        for name in config.state_env_names():
            os.environ.pop(name, None)
        yield reached
