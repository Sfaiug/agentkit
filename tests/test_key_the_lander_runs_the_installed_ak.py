"""The installed ak checks a whole landing line, across its members' launch versions.

Black-box: real lines, suites and installs in a throwaway Home. A wrapper at a version's
bin/ak records the commit of each lander start, its re-exec into a version included.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, Home, rerun_boxed
from fixtures.akinstall import Install
from fixtures.akline import Line, READINGS

# A version's bin/ak: started as `run --lander`, it appends the commit of the checkout above its
# bin/ to ~/lander.code, then runs bin/ak.program.  A script runs in this process, `sys.argv[0]`
# still this path, as Python ak compares it with <checkout>/bin/ak (run.lone_run); anything
# else is exec'd.
WRAPPER = '''#!{python}
import os
from pathlib import Path
import subprocess
import sys

here = Path(__file__).resolve().parent
if sys.argv[1:3] == ["run", "--lander"]:
    with (Path.home() / "lander.code").open("a") as out:
        out.write(subprocess.run(["git", "-C", str(here.parent), "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout)
__file__ = str(here / "ak.program")
with open(__file__, "rb") as program:
    source = program.read()
if not source.startswith(b"#!"):
    os.execv(__file__, sys.argv)
exec(compile(source, __file__, "exec"))
'''


class TheLanderRunsTheInstalledAk(unittest.TestCase):
    def version(self, directory, code):
        path = directory / "run.json"
        state = json.loads(path.read_text())
        state["ak_checkout"] = str(code)
        path.write_text(json.dumps(state))

    def test_a_red_targets_repair_is_checked_past_members_on_other_versions(self):
        line = Line({"t/repair.sh": "test -f repaired.txt\n"})
        self.addCleanup(line.close)
        for files in ({"api.txt": "api\n"}, {"ui.txt": "ui\n"}, {"repaired.txt": "fixed\n"}):
            line.member(files)
        first, second, repair = line.members
        self.version(first, Path(AK).resolve().parent.parent)
        self.version(second, line.home.root / "old-ak")
        self.version(repair, line.home.root / "new-ak")
        tree = line.rig.git("rev-parse", "main^{tree}")
        receipt = Path(line.line).with_suffix(".green").name
        line.home.write(f".agentkit/runs/{receipt}", {"red": {tree: {
            "at": 0, "run": repair.name, "probe": {"sha": line.base}}}})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("land", line.verdict(3), line.runs())
        for n in (1, 2):
            self.assertEqual(set(line.verdict(n)), {"line", "joined"})

    def test_members_on_different_versions_share_one_stack_check(self):
        line = Line({"t/ok.sh": "true\n"})
        self.addCleanup(line.close)
        for n in range(3):
            line.member({f"member-{n}.txt": f"{n}\n"})
            self.version(line.members[-1], line.home.root / f"ak-{n}")
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        for n in (1, 2, 3):
            self.assertIn("land", line.verdict(n), line.runs())
        self.assertEqual(line.whole(), 1, line.runs())

    def test_a_pass_runs_the_installed_code_instead_of_its_first_members(self):
        with Home() as home:
            install = Install(home)
            wrapper = install.seed / "bin" / "ak"
            wrapper.rename(wrapper.with_name("ak.program"))
            wrapper.write_text(WRAPPER.format(python=sys.executable))
            wrapper.chmod(0o755)
            first = install._push("each version names its commit")
            install.git("fetch", "-q", "origin")
            install.git("reset", "--hard", first)
            old = home.root / "old-ak"
            install._git(home.root, "clone", "-q", str(install.path), str(old))
            second = install.advance()
            install.git("fetch", "-q", "origin")
            install.git("reset", "--hard", second)
            line = Line({"t/ok.sh": "true\n"}, home=home)
            line.member({"api.txt": "api\n"})
            self.version(line.members[0], old)
            observed = home.path / "lander.code"

            def starts():
                return observed.read_text().splitlines() if observed.exists() else []
            for entry in (("watch",), ("run", "--lander", line.line)):
                done = home.run(install.ak, *entry, timeout=300,
                                env={"AK_HOST_READINGS": READINGS, "AK_RUN_CODE": str(old)})
                self.assertEqual(done.code, 0, done.out + done.err)
                deadline = time.monotonic() + 120
                while (not ("land" in line.verdict(1) and starts())
                       and time.monotonic() < deadline):
                    time.sleep(0.1)
                self.assertIn("land", line.verdict(1), done.out + done.err)
                self.assertEqual(set(starts()), {second}, entry)
                observed.unlink()


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
