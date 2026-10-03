"""Run both landing parts together, keeping progress live and their outputs separate."""

import shutil
import subprocess
import sys
import tempfile
import time


with tempfile.NamedTemporaryFile() as output, subprocess.Popen(
        [sys.executable, "tests/every_file.py"], stdout=output,
        stderr=subprocess.STDOUT) as files:
    smoke = subprocess.call(["bash", "tests/smoke.sh"], stderr=subprocess.STDOUT)
    # Separate handles keep the reader's position from moving the writer's.
    with open(output.name, "rb") as buffered:
        while True:
            code = files.poll()
            shutil.copyfileobj(buffered, sys.stdout.buffer)
            sys.stdout.buffer.flush()
            # Read after observing exit so the final bytes cannot race the last drain.
            if code is not None:
                break
            time.sleep(0.1)
sys.exit(code or smoke)
