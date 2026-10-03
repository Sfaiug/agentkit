"""Divide the declared suite without changing its checks or keeping shared timing state."""

import os
from pathlib import Path
import re
import sys


def shard(value=None):
    value = os.environ.get("AK_SHARD", "") if value is None else value
    if not value:
        return 1, 1
    if re.fullmatch(r"[1-9][0-9]*/[1-9][0-9]*", value):
        number, total = map(int, value.split("/"))
        if number <= total:
            return number, total
    raise ValueError("AK_SHARD must be k/N with 1 <= k <= N")


def shares(costs, total):
    """Longest first keeps an expensive check or file from lining up with the others."""
    loads, owners = [0] * min(total, len(costs)), {}
    for name in sorted(costs, key=lambda name: (-costs[name], name)):
        piece = min(range(len(loads)), key=lambda piece: (loads[piece], piece))
        owners[name] = piece + 1
        loads[piece] += costs[name]
    return owners


SETUP = "# --- shared setup ----------------------------------------------------------\n"
HEADERS = re.compile(r"^# --- (?:(\w+):)?[^\n]*\n", re.MULTILINE)
# These blocks read fixtures, shell variables or functions made by an earlier block.
DEPENDENCIES = (
    ("retry_start", "9"),
    ("1", "2", "3", "4", "4b", "4c", "4d", "5", "6", "6b", "6d", "31"),
    ("6f", "6g"), ("7", "7b"), ("12", "12b"), ("16", "33"),
    ("20", "20b", "20c", "20d", "20e", "20f", "20g", "35"),
    ("21", "22"), ("23", "23b"), ("25", "25b"),
)
LIVE_CHECKS = {"1", "2", "3", "4", "4b", "4c", "4d", "5", "6", "6b", "6d"}


def smoke_blocks(source):
    source = source[source.index(SETUP):]
    headers = list(HEADERS.finditer(source))
    return [(header[1], source[header.start():headers[i + 1].start()
                              if i + 1 < len(headers) else len(source)])
            for i, header in enumerate(headers)]


def smoke_owners(blocks, root, total, live=False, offline=False):
    groups = {name: group[0] for group in DEPENDENCIES for name in group}
    costs = {}
    for name, body in blocks:
        if name is None:
            continue
        # Source size estimates the work for new checks too; named test files contribute
        # their size, rather than counting a ten-case file like a hundred-case file.
        # Integer units keep independent processes identical even at equal loads.
        cost = len(body.splitlines()) * 20
        for test in set(re.findall(r"\btest_\w+", body)):
            path = root / "tests" / (test + ".py")
            if path.is_file():
                cost += len(path.read_text().splitlines()) * 3
        if name.startswith("offline_") != offline or name in LIVE_CHECKS and not live:
            cost = 0
        if name == "9" and not offline:
            cost = 360 * 300       # its background executor waits out 60s + 300s
        group = groups.get(name, name)
        costs[group] = costs.get(group, 0) + cost
    owners = shares(costs, total)
    return {name: owners[groups.get(name, name)] for name, _ in blocks if name is not None}


def smoke_source(source, root, piece, live=False, offline=False):
    blocks = smoke_blocks(source)
    number, total = piece
    owners = smoke_owners(blocks, root, total, live, offline)
    # A colon leaves an enclosing live/offline guard valid when this piece owns none of it.
    return "".join(body if name is None or owners[name] == number else ":\n"
                   for name, body in blocks)


def main():
    try:
        piece = shard()
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    print(smoke_source(path.read_text(), path.resolve().parents[1], piece,
                       os.environ.get("AGENTKIT_SMOKE_LIVE", "0") == "1",
                       os.environ.get("AGENTKIT_SMOKE_OFFLINE", "0") == "1"), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
