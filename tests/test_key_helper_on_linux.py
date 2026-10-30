"""A suite helper that is a Linux machine with docker runs a suite's pieces as the Mac does.

Its pieces passing there take no turn here; a piece failing there runs again here, and that run
decides.  Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py; ssh runs what it is given on `acme-linux`, a directory with a HOME and
programs of its own: a fake docker, whose containers have `container=docker` in their environment,
and the machine's readings, two CPUs at rest.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akline import Line

# ssh ALIAS COMMAND: COMMAND as the machine's shell runs it, in nothing of this host's environment.
SSH = '#!/bin/bash\nexec env -i HOME={home} PATH={bin}:/usr/bin:/bin bash -c "${{@: -1}}"\n'

# docker, as tools/helper/linux.sh asks it: images and containers are files beside this program,
# and a container runs only an image a build left. Its root is a directory holding its volumes as
# links, its home, its own cgroup's memory.events and the kernel's /proc/vmstat, shared with every
# container and counting one more kill at each read; its command runs with the paths it names
# there.
DOCKER = r"""
import itertools, os, re, shutil, subprocess, sys, threading
from pathlib import Path
state = Path(__file__).resolve().parent.parent / "docker"
images, containers = state / "images", state / "containers"
words = sys.argv[1:]
held = {path.name: path.read_text() for path in containers.glob("*")}    # name: memory
if words[:2] == ["image", "inspect"]:
    sys.exit(not (images / words[2]).exists())
elif words[:2] == ["image", "ls"]:
    print("".join(f"{path.name}\n" for path in images.glob(f"{words[-1]}:*")), end="")
elif words[:2] == ["image", "rm"]:
    for ref in words[2:]:
        (images / ref).unlink()
elif words[0] == "build":    # build -q -t IMAGE -f RECIPE CONTEXT
    assert Path(words[5]).is_file() and Path(words[6]).is_dir()
    (images / words[3]).touch()
elif words[0] == "ps":
    print("".join(f"{name}\n" for name in held), end="")
elif words[0] == "inspect":    # an unknown container fails it, as docker's does
    print("\n".join(held[name] if "Memory" in words[2] else "true" for name in words[3:]))
elif words[0] == "run":
    flags, links = {}, {}
    words.pop(0)
    while words[0].startswith("--"):
        flag = words.pop(0)
        if flag == "--volume":
            outside, inside = words.pop(0).split(":")[:2]
            links[inside] = outside
        elif flag not in ("--rm", "--init"):
            flags[flag] = words.pop(0)
    image, _, script, *args = words
    if not (images / image).exists():
        sys.exit(125)
    root = state / "roots" / flags["--name"]
    shutil.rmtree(root, ignore_errors=True)
    for directory in ("home/ak", "sys/fs/cgroup", "proc"):
        (root / directory).mkdir(parents=True)
    (root / "sys/fs/cgroup/memory.events").write_text("oom_kill 0\n")
    os.mkfifo(root / "proc/vmstat")

    def kills():
        for count in itertools.count(1):
            with open(root / "proc/vmstat", "w") as vmstat:
                vmstat.write(f"oom_kill {count}\n")

    threading.Thread(target=kills, daemon=True).start()
    for inside, outside in links.items():
        (root / inside[1:]).symlink_to(outside)
    (containers / flags["--name"]).write_text(f"{int(flags['--memory'][:-1]) * 1048576}\n")
    text = re.sub(r"(?<![\w.-])/(in|out|mirror|home/ak|sys/fs/cgroup|proc/vmstat)\b",
                  f"{root}/\\1", (root / script[1:]).read_text())
    code = subprocess.run(["bash", "-c", text, script, *args], env={
        "PATH": os.environ["PATH"], "HOME": f"{root}/home/ak", "container": "docker"}).returncode
    (containers / flags["--name"]).unlink()
    sys.exit(code)
"""

# The machine's own programs: docker; its size and load; and the piece's way offline, which
# changes nothing here.
TOOLS = {"docker": f"#!{sys.executable}\n{DOCKER}",
         "nproc": "#!/bin/sh\necho 2\n",
         "uptime": "#!/bin/sh\necho ' 12:00:00 up 1 day,  load average: 0.00, 0.00, 0.00'\n",
         "free": "#!/bin/sh\nprintf '%s\\n' '  total used' 'Mem: 65536 1024'\n",
         "unshare": '#!/bin/sh\nwhile [ "${1#-}" != "$1" ]; do shift; done\nexec "$@"\n',
         "setpriv": '#!/bin/sh\nwhile [ "${1#-}" != "$1" ]; do shift; done\nexec "$@"\n',
         "ip": '#!/bin/sh\n[ "$1" != -o ] || echo "1: lo: <LOOPBACK,UP>"\n'}


class HelperOnLinux(unittest.TestCase):
    def land(self, b):
        """What the lander left its one member waiting on, its suite's runs here and its runs
        on the machine, where `t/b.sh`, in piece 2/2, is `b`."""
        line = Line({"t/a.sh": "true\n", "t/b.sh": b,
                     "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        self.addCleanup(line.close)
        akconfig.write(line.home, ["opus", "astra"], settings={"suite_helper": "acme-linux"})
        machine = line.home.root / "acme-linux"
        for directory in ("home", "bin", "docker/images", "docker/containers"):
            (machine / directory).mkdir(parents=True)
        for name, text in TOOLS.items():
            (machine / "bin" / name).write_text(text)
            (machine / "bin" / name).chmod(0o755)
        line.home.fake("ssh", SSH.format(home=machine / "home", bin=machine / "bin"))
        line.member({"api.txt": "x\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.said = "".join(path.read_text(errors="replace")
                            for path in (line.home.path / ".agentkit").rglob("*.log"))
        there = sorted(tuple(run.split(" ", 2))
                       for log in machine.glob("docker/roots/*/home/ak/work/.git/suite.log")
                       for run in log.read_text().splitlines())
        return line.verdict(1), line.runs(), there

    def test_pieces_passing_there_take_no_turn_here(self):
        verdict, runs, there = self.land("true\n")
        self.assertIn("land", verdict, verdict)
        self.assertEqual((runs, there), ([], [("piece", "1/2", ""), ("piece", "2/2", "")]))

    def test_a_piece_failing_only_there_passes_here_and_lands(self):
        verdict, runs, _ = self.land('[ "$container" != docker ]\n')
        self.assertIn("land", verdict, verdict)
        self.assertEqual(runs, [("alone", ""), ("piece", "2/2", "")])
        self.assertIn("failed on the suite helper acme-linux, then passed on its re-run",
                      self.said)

    def test_a_piece_failing_there_and_here_keeps_the_member_red(self):
        verdict, runs, _ = self.land("! test -f api.txt\n")    # red on the member's tree alone
        self.assertIn("fix", verdict, verdict)
        self.assertEqual(runs[0], ("alone", ""))


if __name__ == "__main__":
    unittest.main()
