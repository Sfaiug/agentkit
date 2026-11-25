"""What a hook leaves running, waited for before its test's sandbox goes.

A hook starts its look detached (hooks/seat-state.sh), and one still writing as the sandbox is
removed brings the removal down: "Directory not empty".  Naming each such process, by a pid it or
its starter writes, misses one never named and one named before it started.  A pipe names
nothing: every process a hook leaves holds the write end that hook was passed, whoever started
it, the kernel closes a process's end as it ends, and the pipe ends once the last of them has.
"""

import os


def pipe(cleanup):
    """The descriptor each hook is passed (`pass_fds`).  The wait `cleanup` takes -- a test's
    `addCleanup`, an `ExitStack`'s `callback` -- closes this process's own end and reads the
    pipe to its end: it returns once no process a hook left is running."""
    read, write = os.pipe()

    def wait():
        os.close(write)
        with open(read, "rb") as ends:
            ends.read()
    cleanup(wait)
    return write
