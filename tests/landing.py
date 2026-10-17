"""Run the static checks, then both landing parts and the gate's contract together, keeping
progress live and outputs separate. Each test that fails is named in the file AK_FAILED names;
with AK_ONLY set only the tests its file lists run (suite_shares.listed)."""

import shutil
import subprocess
import sys
import tempfile
import time

from suite_shares import STATIC_CHECKS, listed, name_failed

only = listed()


def part(*command):
    """`command`, whose last word is its test's ID, or one that runs nothing when AK_ONLY lists
    tests and not that one."""
    return command if only is None or command[-1] in only else (sys.executable, "-c", "")


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
    smoke = subprocess.call(part("bash", "tests/smoke.sh"), stderr=subprocess.STDOUT)
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
# every_file.py named its own failed files before it ended.
name_failed(test for test, red in (("tests/smoke.sh", smoke),
                                   ("tests/gate_contract.py", contract.returncode)) if red)
sys.exit(code or smoke or contract.returncode)
