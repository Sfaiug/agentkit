"""Owner, 28 Oct 2026: ak's checks never hold a login that can renew, and need no login of their
own, so no user signs in twice.

On 28 Oct a check renewed the host's login in the throwaway HOME it was linked into, retiring
the pair every seat held.  So each harness whose manifest lists `[worker] logins` lends a check's
HOME a copy nothing can renew, its adapter's `lend`, of its usual login whatever AGENTKIT_ACCOUNT
names, and nothing goes back; one with none to lend, or no adapter here, lends none.

Usage: python3 -m agentkit.lend <home>
    a line per harness lent, its name and the files it placed, by their path in <home>; exit 1
    saying why where a lend failed or a place it takes in <home> is taken.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import config


def into(home):
    """Lend `home` each harness's login: ({harness: [files placed]}, the epoch second the first
    of them stops authenticating, None where none does).  Where a lend fails or a place it takes
    is taken it raises, leaving none lent: no caller is told what to keep out of what it saves."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **config.account_env(None), **config.provider_env(())}
    lent, ends = {}, []
    try:
        for harness, data in dict(config.manifests()).items():
            if not (data.get("worker", {}).get("logins") and config.adapter_path(harness).exists()):
                continue
            # Lent into a folder of its own, so what it placed is known without its harness's
            # layout, and linked from there into `home`, which refuses a place taken.
            with tempfile.TemporaryDirectory(prefix=".lend-", dir=home) as staging:
                proc = subprocess.run([str(config.adapter(harness)), "lend", staging], env=env,
                                      text=True, stdin=subprocess.DEVNULL, capture_output=True,
                                      timeout=60)   # asking for saved keys boots a server
                if proc.returncode == 1:
                    continue
                if proc.returncode:
                    raise config.Error(f"{harness} lend exited {proc.returncode}: "
                                       f"{proc.stderr.strip()}")
                lent[harness] = []
                for path in sorted(Path(staging).rglob("*")):
                    if path.is_file():
                        place = home / path.relative_to(staging)
                        place.parent.mkdir(parents=True, exist_ok=True)
                        os.link(path, place)
                        lent[harness].append(place)
                if proc.stdout.strip():
                    ends.append(int(proc.stdout))
    except BaseException:
        for place in (place for files in lent.values() for place in files):
            place.unlink()
        raise
    return lent, min(ends, default=None)


if __name__ == "__main__":
    home = Path(sys.argv[1])
    try:
        lent, _ = into(home)
    except (config.Error, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        sys.exit(f"lend: {exc}")
    for harness, files in lent.items():
        print(harness, *(path.relative_to(home) for path in files))
