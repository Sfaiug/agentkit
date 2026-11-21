"""On each machine ak knows, the program a box loads answers that machine's six sync calls with
errno 0 and passes every other call and architecture, by Linux's numbers (fixtures/kernel.py)."""

import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agentkit import syncs
from fixtures.kernel import SYNCS


def answer(program, arch, call):
    steps = [struct.unpack("=HBBI", program[i:i + 8]) for i in range(0, len(program), 8)]
    at, held = 0, None
    while steps[at][0] != 0x06:                 # BPF_RET
        code, yes, no, k = steps[at]
        held = {0: call, 4: arch}[k] if code == 0x20 else held      # a load: call 0, arch 4
        at += 1 + (0 if code == 0x20 else yes if held == k else no)
    return steps[at][3]


class ASyncInABoxIsAnsweredOnEachMachineAkKnows(unittest.TestCase):
    def test_each_machine_answers_its_six_calls_and_passes_the_rest(self):
        self.assertEqual(syncs.CALLS, SYNCS)
        for machine, (arch, calls) in syncs.CALLS.items():
            for call in range(512):
                want = 0x00050000 if call in calls else 0x7FFF0000      # errno 0, else allow
                got = [answer(syncs._program(arch, calls), a, call) for a in (arch, arch ^ 1)]
                self.assertEqual(got, [want, 0x7FFF0000], (machine, call))


if __name__ == "__main__":
    unittest.main()
