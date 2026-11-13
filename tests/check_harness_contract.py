"""Live adapter contract, check 3 of tests/smoke.sh: `python3 tests/check_harness_contract.py
[harness]` runs `ak contract` (agentkit/contract.py) of the program `AK_BIN` names, as
tests/fixtures/akbin.py reads it, and exits as it does.  Imported, it gives smoke.sh's other
checks the program's own answers to what check 3 asks too."""

import os
import sys

if __name__ == "__main__":
    from fixtures.akbin import AK
    os.execv(AK, [AK, "contract", *sys.argv[1:]])

from agentkit.contract import refused, selected_model, spent_until, unavailable  # noqa: E402,F401
