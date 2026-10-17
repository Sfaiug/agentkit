"""The usage probe kills and reaps a detached child on a kernel that does not list children.

A kernel built without CONFIG_PROC_CHILDREN has no `/proc/<pid>/task/<tid>/children`. A
sitecustomize every fixture process loads takes that file away, and a fake harness detaches a
`sleep` into its own session; nothing here reaches a real harness or the network.
"""

import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import usage_probe

NO_CHILDREN_FILE = r'''
import builtins, io, re
opened = io.open
def kernel_without_children(file, *args, **kwargs):
    if re.fullmatch(r"/proc/\d+/task/\d+/children", str(file)):
        raise FileNotFoundError(2, "No such file or directory", str(file))
    return opened(file, *args, **kwargs)
io.open = builtins.open = kernel_without_children
'''

HARNESS = r'''
import os, pathlib, subprocess, sys
try:
    pathlib.Path(f"/proc/{os.getpid()}/task/{os.getpid()}/children").read_text()
    sys.exit("the children file is still there")
except FileNotFoundError:
    pass
child = subprocess.Popen(["sleep", "60"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
pathlib.Path(os.environ["DETACHED"]).write_text(str(child.pid))
print("usage read")
'''


@unittest.skipUnless(sys.platform == "linux", "the subreaper and its children are Linux's")
class WithoutProcChildren(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-no-proc-children-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "sitecustomize.py").write_text(NO_CHILDREN_FILE)
        self.detached = root / "detached"
        self.addCleanup(self.kill_detached)
        env = patch.dict(os.environ, {"PYTHONPATH": str(root), "DETACHED": str(self.detached)})
        env.start()
        self.addCleanup(env.stop)

    def kill_detached(self):
        try:
            os.kill(int(self.detached.read_text()), signal.SIGKILL)
        except (OSError, ValueError):
            pass

    def test_a_detached_child_is_killed_and_reaped_and_the_output_kept(self):
        proc = usage_probe.capture([sys.executable, "-c", HARNESS])
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "usage read\n", ""))
        # Gone: the probe killed and reaped it instead of leaving it to sleep out its minute.
        with self.assertRaises(ProcessLookupError):
            os.kill(int(self.detached.read_text()), 0)


if __name__ == "__main__":
    unittest.main()
