"""`time` as one module sees it, with only that module's own sleeps faked."""

import time


class Clock:
    """`time` as run.py sees it, with only run.py's own sleeps going to `sleep`.

    Patching `time.sleep` itself fakes every wait in the process. `subprocess` waits with
    a timeout by sleeping in small steps, under every timed git, gh or adapter call, and
    the waits that stop a box poll: they would spin, and a fake that records keeps every
    turn of the spin -- hundreds of tiny sleeps by host load, or gigabytes when a turn is
    stopped again and again.
    """

    def __init__(self, sleep):
        self.sleep = sleep

    def __getattr__(self, name):
        return getattr(time, name)
