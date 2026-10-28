"""Choose the declared suite's checks for its mode and divide them, and name those that failed,
without changing a check or keeping shared timing state."""

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


def listed():
    """The test IDs, checkout-relative paths, in the file AK_ONLY names, one per line: the only
    tests to run, whatever the share. None when AK_ONLY is unset: every test runs."""
    path = os.environ.get("AK_ONLY", "")
    return {line.strip() for line in Path(path).read_text().splitlines()} - {""} if path else None


def name_failed(tests, file="AK_FAILED"):
    """Append the failed tests' IDs to the file AK_FAILED names, one per line, if it names one;
    with `file` "AK_RAN", the IDs of the listed tests it runs: a run of AK_ONLY's tests counts
    for none it does not name, as an ID it does not know runs nothing; with "AK_FLAKY", those
    that failed, then passed on a re-run."""
    if os.environ.get(file):
        with open(os.environ[file], "a") as fh:
            fh.writelines(f"{test}\n" for test in tests)


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
    ("1", "2", "3", "3a", "4", "4b", "4c", "4d", "5", "6", "6b", "6d", "31d"),
    ("6f", "6g"), ("7", "7b"), ("12", "12b"), ("16", "33"),
    ("20", "20b", "20c", "20d", "20e", "20f", "20g", "35"),
    ("21", "22"), ("23", "23b"), ("25", "25b"),
)
# The checks that need the outside world: real models, GitHub, Discord, live meters, the shared
# browser and user systemd.  The live mode (tests/live.sh) runs them and nothing else, before a
# host takes new code and when a harness upgrades; the landing suite runs every other check and
# reaches nothing beyond loopback.  Their offline twins run at landing: 19 the delivery path, 41
# and 8a-8f the meters, 20e and 20f the seats, 31b and 31c the MCP wiring.
LIVE_CHECKS = {"1", "2", "3", "3a", "4", "4b", "4c", "4d", "5", "6", "6b", "6d", "6f", "6g",
               "31a", "31d"}
# The checks that read the checkout alone and take seconds: tests/landing.py runs them first in
# every share and stops there when one fails; every_file.py leaves them to it.
STATIC_CHECKS = ("test_dead_code", "test_boundaries", "test_modules_say_what_they_are", "test_docs")


def smoke_blocks(source):
    source = source[source.index(SETUP):]
    headers = list(HEADERS.finditer(source))
    # Check 0 must stop every piece before any unsafe tmux command can run.
    return [(None if header[1] == "0" else header[1],
             source[header.start():headers[i + 1].start()
                    if i + 1 < len(headers) else len(source)])
            for i, header in enumerate(headers)]


def smoke_owners(blocks, root, total, live=False, offline=False):
    groups = {name: group[0] for group in DEPENDENCIES for name in group}
    costs = {}
    mine = [(name, body) for name, body in blocks
            if name is not None and (name in LIVE_CHECKS) == live]
    for name, body in mine:
        # Source size estimates the work for new checks too; named test files contribute
        # their size, rather than counting a ten-case file like a hundred-case file.
        # Integer units keep independent processes identical even at equal loads.
        cost = len(body.splitlines()) * 20
        for test in set(re.findall(r"\btest_\w+", body)):
            path = root / "tests" / (test + ".py")
            if path.is_file():
                cost += len(path.read_text().splitlines()) * 3
        if name.startswith("offline_") != offline:
            cost = 0
        group = groups.get(name, name)
        costs[group] = costs.get(group, 0) + cost
    owners = shares(costs, total)
    return {name: owners[groups.get(name, name)] for name, _ in mine}


def smoke_source(source, root, piece, live=False, offline=False):
    blocks = smoke_blocks(source)
    number, total = piece
    owners = smoke_owners(blocks, root, total, live, offline)
    # A colon leaves an enclosing offline guard valid when this piece owns none of it.
    return "".join(body if name is None or owners.get(name) == number else ":\n"
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
