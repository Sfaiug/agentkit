"""Run the static checks, then both landing parts and the gate's contract together, keeping
progress live and outputs separate. Each test that fails is named in the file AK_FAILED names;
with AK_ONLY set only the tests its file lists run, whatever the share (suite_shares.listed),
each named in the file AK_RAN names, smoke.sh's blocks as `tests/smoke.sh#<check>`. With
AK_ONLY unset and AK_CHANGED naming the paths a change edits, AK_ONLY lists this piece's
(AK_SHARD) share of the tests that change can affect against HEAD's first parent (affected.py)."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from suite_shares import (SMOKE, STATIC_CHECKS, listed, name_failed, shard, shares,
                          smoke_blocks, smoke_owners)


def narrowed():
    """This piece's share of the tests the change AK_CHANGED names can affect, each test in one
    piece, the import check among them; None where every test runs."""
    paths = listed("AK_CHANGED")
    if not paths:
        return None
    # Here, not at the top: only a narrowed run reads them, and every_file.py imports agentkit.
    from affected import selection
    from every_file import IMPORTS, costs
    chosen = selection(".", paths, "HEAD^")
    if chosen is None:
        return None
    offline = os.environ.get("AGENTKIT_SMOKE_OFFLINE", "0") == "1"
    # The blocks this mode runs (smoke_owners). A test file runs alone even where a block runs it
    # too: its text cannot say, as its helpers are shared and an argument picks their module.
    blocks = [(name, body) for name, body in smoke_blocks(Path(SMOKE).read_text())
              if f"{SMOKE}#{name}" in chosen and name.startswith("offline_") == offline]
    files = [Path(test) for test in (*chosen, IMPORTS) if "#" not in test]
    number, total = shard()
    owners = smoke_owners(blocks, Path(), total, offline=offline)
    return ([str(path) for path, owner in shares(costs(Path(), files), total).items()
             if owner == number]
            + [f"{SMOKE}#{name}" for name, owner in owners.items() if owner == number])


only = listed()
if only is not None:
    # A listed smoke.sh runs whole: it would otherwise run only this share.
    os.environ["AK_SHARD"] = "1/1"
elif (only := narrowed()) is not None:
    # The list lives as long as this script; the piece keeps its share, smoke.sh its own HOME.
    listing = tempfile.NamedTemporaryFile("w", prefix="ak-narrowed-")
    listing.writelines(f"{test}\n" for test in only)
    listing.flush()
    os.environ["AK_ONLY"] = listing.name
# Who started this script may not ask what ran (gate.run_suite), yet a red smoke.sh is named by it.
unasked = tempfile.NamedTemporaryFile(prefix="ak-ran-")
ran = Path(os.environ.get("AK_RAN") or unasked.name)
os.environ["AK_RAN"] = str(ran)


def part(*command):
    """`command`, whose last word is its test's ID, or one that runs nothing when AK_ONLY lists
    tests and neither that one nor a block of it; a listed one is named as run, a block by
    smoke.sh itself (suite_shares.smoke_source)."""
    if only is not None and command[-1] in only:
        name_failed([command[-1]], "AK_RAN")
    return (command if only is None or any(test.split("#")[0] == command[-1] for test in only)
            else (sys.executable, "-c", ""))


# A red static check ends the share in seconds, not after its whole run and the re-run alone.
# All of them run, so one landing names every one that fails.
failed = [check for check in (f"tests/{name}.py" for name in STATIC_CHECKS)
          if subprocess.call(part(sys.executable, check), stderr=subprocess.STDOUT)]
if failed:
    name_failed(failed)
    sys.exit(1)

# every_file.py re-runs a failed file with nothing of this piece beside it: it waits for the
# end of its standard input, closed below once smoke.sh and the contract have ended, and by
# `files` itself, before it waits for the runner, when an error ends this script early.
with tempfile.NamedTemporaryFile() as output, tempfile.NamedTemporaryFile() as checked, \
        subprocess.Popen(part(sys.executable, "tests/gate_contract.py"), stdout=checked,
                         stderr=subprocess.STDOUT) as contract, \
        subprocess.Popen([sys.executable, "tests/every_file.py", ".", "0"],
                         stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT) as files:
    smoke = subprocess.call(part("bash", SMOKE), stderr=subprocess.STDOUT)
    # Separate handles keep the reader's position from moving the writer's.
    with open(output.name, "rb") as buffered:
        while True:
            code = files.poll()
            # The contract may outlast smoke.sh: the files' progress streams meanwhile.
            if contract.poll() is not None:
                files.stdin.close()
            shutil.copyfileobj(buffered, sys.stdout.buffer)
            sys.stdout.buffer.flush()
            # Read after observing exit so the final bytes cannot race the last drain.
            if code is not None:
                break
            time.sleep(0.1)
    with open(checked.name, "rb") as contract_output:
        contract.wait()
        shutil.copyfileobj(contract_output, sys.stdout.buffer)
        sys.stdout.buffer.flush()
# every_file.py named its own failed files before it ended. A red smoke.sh is named by its exit
# alone, whatever made it red: as itself, or where AK_ONLY lists its blocks by each that started.
name_failed(test for test, red in ((SMOKE, smoke), ("tests/gate_contract.py", contract.returncode))
            if red and (only is None or test in only))
if smoke and ran.exists():
    name_failed(test for test in ran.read_text().splitlines() if test.startswith(f"{SMOKE}#"))
sys.exit(code or smoke or contract.returncode)
