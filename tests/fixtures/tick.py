"""A test's tick: `watch.main` runs only the passes a test names, under no login of the caller's.

A test names a pass by its name in `watch.local_passes`, and a name no pass has is refused: it
would still the very pass the test meant.  Every other pass of that table is a no-op, one added
to it later included: a test listing the passes to stub would run a new one for real, and the
weekly audit pass opened a real seat that way.  HOME is the test's temporary directory, and no
login of the caller's is left for a pass to find its way back to the owner's with: no harness's
state or login root (CLAUDE_CONFIG_DIR among them), ak's own adapters' as well as any a test's
fake adapters declare instead, no account or provider ak names, no credential.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from agentkit import config, watch

# a variable that holds a credential, whichever harness or tool reads it
CREDENTIAL = re.compile(r"(?:^|_)(?:TOKEN|KEY|SECRET|PASSWORD|AUTH)$")


def logins():
    """The caller's variables a pass could reach a login of theirs by."""
    names = config.state_env_names() | {config.ACCOUNT_ENV, config.PROVIDER_ENV}
    # a test's fake adapters or checkout of its own replace the declarations of the adapters ak
    # ships, never the caller's logins: those are read from this checkout
    with patch.dict(os.environ), patch.object(config, "REPO", REPO):
        os.environ.pop(config.ADAPTER_DIR_ENV, None)
        names |= config.state_env_names()
    return names | {name for name in os.environ if CREDENTIAL.search(name)}


@contextmanager
def only_passes(home, *named):
    """Every pass the tick reached, named or not, in its order."""
    table, reached = watch.local_passes, []

    def passes(state, dry_run, log):
        found = tuple(table(state, dry_run, log))
        missing = {*named} - {name for name, _, _ in found}
        assert not missing, f"no pass is named {', '.join(sorted(missing))}"
        for name, step, also_dry in found:
            def reach(name=name, step=step):
                reached.append(name)
                if name in named:
                    step()
            yield name, reach, also_dry

    with patch.object(watch, "local_passes", passes), \
            patch.dict(os.environ, {"HOME": str(home)}):
        for name in logins():
            os.environ.pop(name, None)
        yield reached


if __name__ == "__main__":
    # `tick.py [--dry-run] [PASS...]`: `ak watch` as a check's subprocess has it, in its HOME
    dry = sys.argv[1:2] == ["--dry-run"]
    with only_passes(Path.home(), *sys.argv[1 + dry:]):
        sys.exit(watch.main(sys.argv[1:1 + dry]))
