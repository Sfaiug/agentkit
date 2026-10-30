"""A suite helper that is a Linux machine with docker, for black-box tests: ssh runs what it is
given on it, a directory with a HOME and programs of its own: a fake docker, whose containers have
`container=docker` in their environment, and the machine's readings, two CPUs.

    from fixtures import akmachine
    machine = akmachine.install(home)    # every alias ssh is given reaches it
    logs = machine.glob("docker/roots/*/home/ak/work/.git/suite.log")    # each piece's clone
"""

import sys

# ssh ALIAS COMMAND: COMMAND as the machine's shell runs it, in nothing of this host's environment.
SSH = '#!/bin/bash\nexec env -i HOME={home} PATH={bin}:/usr/bin:/bin bash -c "${{@: -1}}"\n'

# docker, as tools/helper/linux.sh asks it: images and containers are files beside this program,
# and a container runs only an image a build left. Its root is a directory holding its volumes as
# links, its home and /tmp, its own cgroup's memory.events and the kernel's /proc/vmstat, shared
# with every container and counting one more kill at each read; its command runs with the paths it
# names there. A volume at a path of this host's own, a turn's, is bound there by bubblewrap; one
# nested in another, its mount point missing there, makes it as docker does, as root: here,
# read-only.
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
    for directory in ("home/ak", "sys/fs/cgroup", "proc", "tmp"):
        (root / directory).mkdir(parents=True)
    (root / "sys/fs/cgroup/memory.events").write_text("oom_kill 0\n")
    os.mkfifo(root / "proc/vmstat")

    def kills():
        for count in itertools.count(1):
            with open(root / "proc/vmstat", "w") as vmstat:
                vmstat.write(f"oom_kill {count}\n")

    threading.Thread(target=kills, daemon=True).start()
    points = [Path(place, inside[len(over) + 1:]) for inside in links
              for over, place in links.items() if inside.startswith(f"{over}/")]
    made = {path for point in points for path in (point, *point.parents) if not path.exists()}
    for point in points:
        point.mkdir(parents=True, exist_ok=True)
    for path in made:
        path.chmod(0o555)
    binds = []
    for inside, outside in sorted(links.items()):
        if inside[1:] in ("in", "out", "mirror", "harness"):
            (root / inside[1:]).symlink_to(outside)
        else:
            binds += ["--bind", outside, inside]
    (containers / flags["--name"]).write_text(f"{int(flags['--memory'][:-1]) * 1048576}\n")
    text = re.sub(r"(?<![\w.-])/(in|out|mirror|harness|home/ak|sys/fs/cgroup|proc/vmstat)\b",
                  f"{root}/\\1", (root / script[1:]).read_text())
    bwrap = ["bwrap", "--dev-bind", "/", "/", *binds, "--"] if binds else []
    code = subprocess.run([*bwrap, "bash", "-c", text, script, *args], env={
        "PATH": os.environ["PATH"], "HOME": f"{root}/home/ak", "TMPDIR": f"{root}/tmp",
        "container": "docker"}).returncode
    (containers / flags["--name"]).unlink()
    sys.exit(code)
"""

# The machine's own programs: docker; its size; the piece's way offline, which changes nothing
# here; and a curl that reaches nothing until a test gives it its own.
TOOLS = {"docker": f"#!{sys.executable}\n{DOCKER}",
         "nproc": "#!/bin/sh\necho 2\n",
         "free": "#!/bin/sh\nprintf '%s\\n' '  total used' 'Mem: 65536 1024'\n",
         "unshare": '#!/bin/sh\nwhile [ "${1#-}" != "$1" ]; do shift; done\nexec "$@"\n',
         "setpriv": '#!/bin/sh\nwhile [ "${1#-}" != "$1" ]; do shift; done\nexec "$@"\n',
         "ip": '#!/bin/sh\n[ "$1" != -o ] || echo "1: lo: <LOOPBACK,UP>"\n',
         "curl": "#!/bin/sh\nexit 7\n"}


def install(home):
    """Make `home`'s ssh reach a machine of its own; its directory."""
    machine = home.root / "machine"
    for directory in ("home", "bin", "docker/images", "docker/containers"):
        (machine / directory).mkdir(parents=True)
    for name, text in TOOLS.items():
        (machine / "bin" / name).write_text(text)
        (machine / "bin" / name).chmod(0o755)
    home.fake("ssh", SSH.format(home=machine / "home", bin=machine / "bin"))
    return machine
