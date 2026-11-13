"""A sync to disk asked inside a box returns 0 at once, the kernel's filesystems never reached.

Nothing written in a box has to survive a crash of the machine: a check's files are scratch, and
a turn's work is redone by the run that resumes it.  Yet on ext4 each fsync makes the journal
commit, and while it is full every writer on the host waits for room: on 12 Nov 2026 boxes
asked 50 to 110 a second, and a check of half an hour took over two hours.  A seccomp program
bubblewrap loads answers those calls for every program in the box, one calling the kernel itself
(a Go binary) too, which preloading libeatmydata would miss.
"""

import os
import struct
from contextlib import contextmanager

# For each machine ak runs on: its audit architecture, and the numbers there of fsync,
# fdatasync, sync, syncfs, msync and sync_file_range.
CALLS = {"x86_64": (0xC000003E, (74, 75, 162, 306, 26, 277)),
         "aarch64": (0xC00000B7, (82, 83, 81, 267, 227, 84))}


def _program(arch, calls):
    """Classic BPF over seccomp_data, whose call number is at 0 and architecture at 4: a call
    of another architecture, a 32-bit program's, numbers its calls otherwise and passes."""
    load, equal, ret = 0x20, 0x15, 0x06     # BPF_LD|BPF_W|BPF_ABS, BPF_JMP|BPF_JEQ|BPF_K, BPF_RET
    allow, errno_0 = 0x7FFF0000, 0x00050000     # SECCOMP_RET_ALLOW, SECCOMP_RET_ERRNO | 0
    steps = [(load, 0, 0, 4), (equal, 0, len(calls) + 1, arch), (load, 0, 0, 0),
             *((equal, len(calls) - i, 0, call) for i, call in enumerate(calls)),
             (ret, 0, 0, allow), (ret, 0, 0, errno_0)]
    return b"".join(struct.pack("=HBBI", *step) for step in steps)


@contextmanager
def ignored():
    """Yield bubblewrap's arguments that load the program, and the descriptors they name, to pass
    on to it; none on another machine, whose box stays as it was."""
    machine = CALLS.get(os.uname().machine)
    if machine is None:
        yield [], ()
        return
    read, write = os.pipe()
    try:
        # A pipe holds far more than the program's few instructions: the write never waits.
        with open(write, "wb") as pipe:
            pipe.write(_program(*machine))
        yield ["--seccomp", str(read)], (read,)
    finally:
        os.close(read)
