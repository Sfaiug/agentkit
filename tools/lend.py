"""Place a lent login where a turn run with HOME=<home> reads it, and say when it lapses.

Usage: <lent> | python3 tools/lend.py <home> <path>

Every adapter's `lend` pipes here `{"ends": <epoch second or null>, "login": <the copy>}`:
the copy goes to <home>/<path>, 0600, its folders made on the way, and `ends` is printed where
there is one.  Exit 2, writing nothing, where <home> is this HOME, whose own login the copy
would stand in for, or anything is at <path> already, the login itself by another name included.
"""
import json
import os
from pathlib import Path
import sys

home, path = sys.argv[1], sys.argv[2]
lent = json.load(sys.stdin)
dest = Path(home, path)
if Path(home).resolve() == Path(os.environ["HOME"]).resolve():
    print(f"lend: {home} is this HOME; lend into another", file=sys.stderr)
    sys.exit(2)
try:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print(f"lend: {dest} is there already; lend into a HOME holding no login", file=sys.stderr)
    sys.exit(2)
with os.fdopen(fd, "w") as out:
    json.dump(lent["login"], out)
if lent["ends"] is not None:
    print(lent["ends"])
