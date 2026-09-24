"""Return to the caller a login a harness renewed in an acceptance gate's sandbox HOME.

Usage: merge_logins.py <sandbox HOME> <caller's Claude .credentials.json> <caller's Grok auth.json>

Both gates link the caller's login files into their sandbox, so a harness that renews in
place renews the caller's own login.  Claude and Grok rename a fresh file over theirs
instead, which leaves the renewed login -- perhaps the only one that still works -- in the
sandbox.  Only valid tokens with a later expiry than the caller's current login go back,
never a failed refresh's cleared login.  They go back whole: the merged login is written
beside the caller's file and renamed over the path it resolves to, so no reader ever sees
half a login and a caller-side link stays a link.  An empty path is a login not borrowed.
"""
from contextlib import nullcontext
from datetime import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

home = Path(sys.argv[1])
def expiry(entry, field):
    try:
        value = entry.get(field)
        seconds = (float(value) / 1000 if field == 'expiresAt' else
                   datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())
        return seconds if math.isfinite(seconds) else 0
    except (AttributeError, TypeError, ValueError):
        return 0

for relative, source, kind in (('.claude/.credentials.json', sys.argv[2], 'claude'),
                               ('.grok/auth.json', sys.argv[3], 'grok')):
    src, dst = home / relative, Path(source)
    if not source or src.is_symlink() or not src.is_file() or not dst.is_file():
        continue
    try:
        fresh = json.loads(src.read_text())
    except ValueError:
        continue
    if not isinstance(fresh, dict):
        continue
    # Grok's own refreshers use this same flock; no independent sandbox lock can protect it.
    with open(str(dst) + '.lock', 'a') if kind == 'grok' else nullcontext() as lock:
        if lock is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        current = json.loads(dst.read_text())
        changed = False
        for key, entry in fresh.items():
            if kind == 'claude' and key != 'claudeAiOauth':
                continue
            fields = ('accessToken', 'refreshToken') if kind == 'claude' else ('key',)
            field = 'expiresAt' if kind == 'claude' else 'expires_at'
            if (not isinstance(entry, dict) or
                    not all(isinstance(entry.get(k), str) and entry[k].strip() for k in fields) or
                    expiry(entry, field) <= max(time.time(), expiry(current.get(key, {}), field))):
                continue
            current[key] = entry
            changed = True
        if changed:
            target = dst.resolve()
            fd, beside = tempfile.mkstemp(prefix=f'.{target.name}.', dir=target.parent)
            try:
                with os.fdopen(fd, 'w') as out:
                    out.write(json.dumps(current) + '\n')
                shutil.copymode(target, beside)
                os.replace(beside, target)
            except BaseException:
                os.unlink(beside)
                raise
