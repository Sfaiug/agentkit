"""Run the static checks, then both landing parts and the gate's contract together, keeping
progress live and outputs separate. Each test that fails is named in the file AK_FAILED names;
with AK_ONLY set only the tests its file lists run, whatever the share (suite_shares.listed),
each named in the file AK_RAN names, smoke.sh's blocks as `tests/smoke.sh#<check>`."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from suite_shares import SMOKE, STATIC_CHECKS, listed, name_failed, smoke_share

only = listed()
if only is not None:
    # A listed smoke.sh runs whole: it would otherwise run only this share.
    os.environ["AK_SHARD"] = "1/1"
# Who started this script may not ask what ran (gate.run_suite), yet a red smoke.sh is named by it.
unasked = tempfile.NamedTemporaryFile(prefix="ak-ran-")
ran = Path(os.environ.get("AK_RAN") or unasked.name)
os.environ["AK_RAN"] = str(ran)
# smoke.sh names in it the block of each check that fails (acceptance.sh's `no`).
blocks = tempfile.NamedTemporaryFile(prefix="ak-smoke-failed-")
os.environ["AK_SMOKE_FAILED"] = blocks.name


def part(*command):
    """`command`, whose last word is its test's ID, or one that runs nothing when AK_ONLY lists
    tests and neither that one nor a block of it; a listed one is named as run, a block by
    smoke.sh itself (suite_shares.smoke_source)."""
    if only is not None and command[-1] in only:
        name_failed([command[-1]], "AK_RAN")
    return (command if only is None or any(test.split("#")[0] == command[-1] for test in only)
            else (sys.executable, "-c", ""))


def status(code):
    """The exit a shell gives `code`, a part's: one a signal ended exits 128 + its number, so a
    piece the kernel killed for memory is run again, never a red (gate._SuiteMeasure.starved)."""
    return 128 - code if code < 0 else code


# A red static check ends the share in seconds, not after its whole run and the re-run alone.
# All of them run, so one landing names every one that fails.
codes = {check: subprocess.call(part(sys.executable, check), stderr=subprocess.STDOUT)
         for check in (f"tests/{name}.py" for name in STATIC_CHECKS)}
if failed := [check for check, code in codes.items() if code]:
    name_failed(failed)
    sys.exit(status(codes[failed[0]]))

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
# every_file.py named its own failed files before it ended. smoke.sh's exit alone says it is red,
# whatever made it so: it is named by each block a check failed in, once; where none did, by each
# listed block that started, or with none listed by each block of its share, so its run alone is
# that share again, not every share's; or else as itself.
if smoke:
    started = ran.read_text().splitlines() if ran.exists() else []
    name_failed(dict.fromkeys(Path(blocks.name).read_text().splitlines())
                or [test for test in started if test.startswith(f"{SMOKE}#")]
                or (smoke_share(Path(SMOKE)) if only is None else []) or [SMOKE])
if contract.returncode:
    name_failed(["tests/gate_contract.py"])
sys.exit(status(code or smoke or contract.returncode))
