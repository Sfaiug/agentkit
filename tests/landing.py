"""Run the static checks, then both landing parts and the gate's contract together, keeping
progress live and outputs separate."""

import shutil
import subprocess
import sys
import tempfile
import time

from suite_shares import STATIC_CHECKS

# A red static check ends the share in seconds, not after its whole run and the re-run alone.
# All of them run, so one landing names every one that fails.
if any([subprocess.call([sys.executable, f"tests/{name}.py"], stderr=subprocess.STDOUT)
        for name in STATIC_CHECKS]):
    sys.exit(1)

# every_file.py re-runs a failed file with nothing of this piece beside it: it waits for the
# end of its standard input, closed below once smoke.sh and the contract have ended, and by
# `files` itself, before it waits for the runner, when an error ends this script early.
with tempfile.NamedTemporaryFile() as output, tempfile.NamedTemporaryFile() as checked, \
        subprocess.Popen([sys.executable, "tests/gate_contract.py"], stdout=checked,
                         stderr=subprocess.STDOUT) as contract, \
        subprocess.Popen([sys.executable, "tests/every_file.py", ".", "0"],
                         stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT) as files:
    smoke = subprocess.call(["bash", "tests/smoke.sh"], stderr=subprocess.STDOUT)
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
sys.exit(code or smoke or contract.returncode)
