"""tools/join.sh, piped into `bash -s -- KEY [tailscale]` as root, makes a Debian or Ubuntu machine
ready for ak and prints the address the home reaches it by: the user ak holding KEY on a line of
its own where only ak and root write, docker, git, jq and sshd, ak in group docker, and sshd's
settings, those it knows; with `tailscale`, Tailscale and its login on a machine on no tailnet.
Run again it changes nothing.  Elsewhere, or cut short, it changes nothing.  A machine ak rents
runs it after its own mounts, holding the setup's commands of 13 Nov 2026 in their order.

Black-box: bubblewrap binds a directory of the test's over each of root's files the script reaches,
and PATH holds only stand-ins for root's programs, each logging its words and the key and sshd
files as they were then; apt-get makes the programs a package brings.  Root's umask lets its group
write, as some systems' does.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from agentkit import google_cloud

DEBIAN = 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\n'
JOIN = (REPO / "tools/join.sh").read_text()
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAcme ak@acme-home"
SSHD = "MaxStartups 500:30:1000\nPerSourcePenalties no\n"
LINK = "https://login.tailscale.com/a/1a2b3c4d"
TAILNET_NAME = "box-1.tail1a2b3.ts.net"
# A rented machine's setup on 13 Nov 2026, before tools/join.sh, as Google was given it.
TODAY = f"""#!/bin/bash
set -e
useradd -m -s /bin/bash ak
mkdir -p /var/lib/docker ~ak/.agentkit-helper ~ak/.ssh
mount -t tmpfs -o size=70% tmpfs /var/lib/docker
mount -t tmpfs -o size=70% tmpfs ~ak/.agentkit-helper
echo '{KEY}' >~ak/.ssh/authorized_keys
chown -R ak: ~ak
apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -qy docker.io docker-cli git jq
usermod -aG docker ak
printf 'MaxStartups 500:30:1000\\nPerSourcePenalties no\\n' >/etc/ssh/sshd_config.d/ak.conf
systemctl reload ssh
touch /run/ak-ready
"""
# Root's programs, one program under each name; the machine's state is files beside bin/.
STANDIN = """#!{python} -I
import json, os, shutil, sys
from pathlib import Path
HOST = "/usr/bin:/bin"      # where the real programs are
me, words = Path(sys.argv[0]), sys.argv[1:]
root, name = me.parent.parent, me.name
world = json.loads((root / "world.json").read_text())
keys, conf = Path("/home/ak/.ssh/authorized_keys"), Path("/etc/ssh/sshd_config.d/ak.conf")
def read(path):
    return path.read_text() if path.exists() else None
def sshd_test(options):    # what sshd -t says of its settings and `options`
    for line in [*(read(conf) or "").splitlines(), *options]:
        if line.split(" ")[0] in world["refuses"]:
            print(f"command-line line 0: Bad configuration option: {{line}}", file=sys.stderr)
            return 255
    return 0
with (root / "log").open("a") as log:
    print(json.dumps({{"run": [name, *words], "keys": read(keys), "sshd": read(conf),
                      "frontend": os.environ.get("DEBIAN_FRONTEND")}}), file=log)
if name in ("mkdir", "touch"):
    os.execv(shutil.which(name, path=HOST), [name, *words])
elif name == "useradd":     # -m -s SHELL USER
    with open("/etc/passwd", "a") as passwd:
        print(f"{{words[3]}}:x:1001:1001::/home/{{words[3]}}:{{words[2]}}", file=passwd)
    os.mkdir(f"/home/{{words[3]}}")
elif name == "usermod":     # -aG GROUP USER
    groups = Path("/etc/group").read_text().splitlines()
    mine = [n for n, line in enumerate(groups) if line.startswith(f"{{words[1]}}:")]
    if not mine:
        sys.exit(f"usermod: group '{{words[1]}}' does not exist")
    *group, held = groups[mine[0]].split(":")
    groups[mine[0]] = ":".join([*group, ",".join(sorted({{*held.split(","), words[2]}} - {{""}}))])
    Path("/etc/group").write_text("\\n".join(groups) + "\\n")
elif name == "apt-get" and words[0] == "install":
    for package in words[2:]:
        if package == "docker-cli" and not world["docker_cli"]:
            sys.exit("E: Unable to locate package docker-cli")
        with (root / "installed").open("a") as installed:
            print(package, file=installed)
        made = {{"docker.io": ["docker", "dockerd"], "openssh-server": ["sshd"]}}
        for program in made.get(package, [package]):    # jq real: it reads Tailscale's answer
            if not (root / "bin" / program).exists():
                (root / "bin" / program).symlink_to(shutil.which(program, path=HOST)
                                                    if program == "jq" else me.resolve())
        if package == "openssh-server":
            os.makedirs("/etc/ssh/sshd_config.d", exist_ok=True)
        if package == "docker.io" and "docker:" not in Path("/etc/group").read_text():
            with open("/etc/group", "a") as group:
                print("docker:x:999:", file=group)
elif name == "apt-cache":   # show docker-cli
    sys.exit(0 if world["docker_cli"] else 100)
elif name == "sshd":        # -t [-o SETTING]
    sys.exit(sshd_test(words[2:]))
elif name == "systemctl" and words[0] == "is-active":     # -q ssh
    sys.exit(0 if world["ssh_active"] else 3)
elif name == "systemctl":   # reload or start ssh: Debian's unit runs sshd -t first
    if sshd_test([]) or words[0] == "reload" and not world["ssh_active"]:
        sys.exit(1)
    world["ssh_active"] = True
    (root / "world.json").write_text(json.dumps(world))
elif name == "curl":        # Tailscale's installer
    print(f"PATH={{HOST}} ln -s {{me.resolve()}} {{root}}/bin/tailscale")
elif name == "tailscale":
    if words == ["up"]:
        print(f"To authenticate, visit:\\n\\n\\t{link}\\n", file=sys.stderr)
        (root / "tailnet").touch()
    elif not (root / "tailnet").exists():
        print("Logged out.")
        sys.exit(1)
    elif "--json" in words:
        print(json.dumps({{"Self": {{"DNSName": "{name}."}}}}))
"""
BWRAP = shutil.which("bwrap")
PROGRAMS = ("useradd", "usermod", "chown", "mount", "mkdir", "touch", "apt-get", "apt-cache",
            "systemctl", "curl")


@unittest.skipUnless(BWRAP, "no bubblewrap here to bind root's files")
class OneLineMakesALinuxMachineReady(unittest.TestCase):
    def machine(self, system=DEBIAN, docker_cli=True, refuses=(), sshd=True, ssh_active=True):
        """A machine's root as files: none of ak's, sshd's settings directory empty."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        for path in ("bin", "home", "ssh/sshd_config.d" if sshd else "ssh", "lib", "run"):
            (root / path).mkdir(parents=True)
        (root / "os-release").write_text(system)
        (root / "passwd").write_text("root:x:0:0:root:/root:/bin/bash\n")
        (root / "group").write_text("root:x:0:\n")
        (root / "world.json").write_text(json.dumps({"docker_cli": docker_cli, "ssh_active":
                                                     ssh_active, "refuses": list(refuses)}))
        standin = root / "standin"
        standin.write_text(STANDIN.format(python=sys.executable, link=LINK, name=TAILNET_NAME))
        standin.chmod(0o755)
        for name in PROGRAMS + ("sshd",) * sshd:
            (root / "bin" / name).symlink_to(standin)
        for name in ("id", "grep", "sh", "tail", "chmod"):
            (root / "bin" / name).symlink_to(shutil.which(name))
        return root

    def run_on(self, root, script, *words):
        """`script` piped into bash as root on `root`'s machine, named box-1: its output, and the
        programs it ran."""
        (root / "log").write_text("")
        binds = [("os-release", Path("/etc/os-release").resolve()), ("passwd", "/etc/passwd"),
                 ("group", "/etc/group"), ("home", "/home"), ("ssh", "/etc/ssh"),
                 ("lib", "/var/lib"), ("run", "/run")]
        ran = subprocess.run(
            [BWRAP, "--ro-bind", "/", "/", "--dev-bind", "/dev", "/dev", "--bind", root, root,
             *(arg for mine, path in binds for arg in ("--bind", root / mine, path)),
             "--unshare-net", "--unshare-uts", "--hostname", "box-1",
             "--", "/bin/bash", "-s", "--", *words],
            input=script, env={"PATH": str(root / "bin")}, umask=0o002, capture_output=True,
            text=True, timeout=120)
        return ran, [json.loads(line) for line in (root / "log").read_text().splitlines()]

    def state(self, root):
        """Every file of the machine, with what it holds, and where each link leads."""
        return {str(path.relative_to(root)): os.readlink(path).removeprefix(str(root))
                if path.is_symlink() else
                path.read_text() if path.is_file() else None
                for path in sorted(root.rglob("*")) if path.name != "log"}

    def address(self, ran):
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        return ran.stdout.splitlines()[-1]

    def test_a_debian_machine_gets_ak_its_key_docker_and_sshds_settings(self):
        root = self.machine()
        ran, log = self.run_on(root, JOIN, KEY)
        self.assertEqual(self.address(ran), "ak@box-1")
        runs = [one["run"] for one in log]
        self.assertIn(["useradd", "-m", "-s", "/bin/bash", "ak"], runs)
        self.assertIn("ak:x:1001:1001::/home/ak:/bin/bash\n", (root / "passwd").read_text())
        self.assertEqual((root / "home/ak/.ssh/authorized_keys").read_text(), KEY + "\n")
        self.assertEqual([oct(path.stat().st_mode & 0o022) for path in (
            root / "home/ak", root / "home/ak/.ssh", root / "home/ak/.ssh/authorized_keys")],
            ["0o0"] * 3)     # what sshd's StrictModes asks of them
        chowned = next(one for one in log if one["run"] == ["chown", "-R", "ak:", "/home/ak"])
        self.assertEqual(chowned["keys"], KEY + "\n")
        installed = next(one for one in log if one["run"][:2] == ["apt-get", "install"])
        self.assertEqual((installed["run"], installed["frontend"]), (
            ["apt-get", "install", "-qy", "docker.io", "docker-cli", "git", "jq"],
            "noninteractive"))
        self.assertIn("docker:x:999:ak\n", (root / "group").read_text())
        self.assertEqual((root / "ssh/sshd_config.d/ak.conf").read_text(), SSHD)
        reloaded = next(one for one in log if one["run"] == ["systemctl", "reload", "ssh"])
        self.assertEqual(reloaded["sshd"], SSHD)

    def test_an_sshd_that_refuses_per_source_penalties_gets_the_rest(self):
        root = self.machine(refuses=["PerSourcePenalties"])
        ran, log = self.run_on(root, JOIN, KEY)
        self.assertEqual(self.address(ran), "ak@box-1")
        reloaded = next(one for one in log if one["run"] == ["systemctl", "reload", "ssh"])
        self.assertEqual(reloaded["sshd"], "MaxStartups 500:30:1000\n")

    def test_where_docker_io_holds_dockers_client_no_docker_cli_is_asked_for(self):
        root = self.machine(docker_cli=False)
        ran, log = self.run_on(root, JOIN, KEY)
        self.assertEqual(self.address(ran), "ak@box-1")
        self.assertIn(["apt-get", "install", "-qy", "docker.io", "git", "jq"],
                      [one["run"] for one in log])

    def test_a_machine_with_dockers_client_alone_gets_its_daemon(self):
        root = self.machine()
        for program in ("docker", "git", "jq"):
            (root / "bin" / program).symlink_to(root / "standin")
        ran, log = self.run_on(root, JOIN, KEY)
        self.assertEqual(self.address(ran), "ak@box-1")
        self.assertIn("docker.io", (root / "installed").read_text().split())

    def test_a_machine_without_sshd_gets_it_running_with_its_settings(self):
        root = self.machine(sshd=False, ssh_active=False)    # as Ubuntu's socket leaves it
        ran, log = self.run_on(root, JOIN, KEY)
        self.assertEqual(self.address(ran), "ak@box-1")
        self.assertIn("openssh-server", (root / "installed").read_text().split())
        started = next(one for one in log if one["run"] == ["systemctl", "start", "ssh"])
        self.assertEqual(started["sshd"], SSHD)
        self.assertTrue(json.loads((root / "world.json").read_text())["ssh_active"])

    def test_a_key_file_whose_last_line_lacks_its_newline_keeps_it_and_gets_the_key(self):
        root = self.machine()
        other = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOther ak@acme-laptop"
        (root / "passwd").write_text("ak:x:1001:1001::/home/ak:/bin/bash\n")
        (root / "home/ak/.ssh").mkdir(parents=True)
        (root / "home/ak/.ssh/authorized_keys").write_text(other)
        self.address(self.run_on(root, JOIN, KEY)[0])
        self.assertEqual((root / "home/ak/.ssh/authorized_keys").read_text(),
                         f"{other}\n{KEY}\n")

    def test_with_tailscale_a_machine_on_no_tailnet_gets_it_and_its_login(self):
        root = self.machine()
        ran, log = self.run_on(root, JOIN, KEY, "tailscale")
        self.assertEqual(self.address(ran), f"ak@{TAILNET_NAME}")
        self.assertIn(LINK, ran.stderr)
        runs = [one["run"] for one in log]
        self.assertIn(["curl", "-fsSL", "https://tailscale.com/install.sh"], runs)
        self.assertIn(["tailscale", "up"], runs)

    def test_run_again_it_changes_nothing_and_prints_the_same_address(self):
        root = self.machine()
        first = self.address(self.run_on(root, JOIN, KEY, "tailscale")[0])
        made = self.state(root)
        ran, log = self.run_on(root, JOIN, KEY, "tailscale")
        self.assertEqual(self.address(ran), first)
        self.assertEqual(self.state(root), made)
        runs = [one["run"] for one in log]
        self.assertEqual([one for one in runs if one[0] in ("useradd", "apt-get", "curl")
                          or one == ["tailscale", "up"]], [])

    def test_another_system_changes_nothing_says_which_it_sets_up_and_exits_2(self):
        root = self.machine(system="ID=kali\nID_LIKE=debian\n")    # apt-get and all
        before = self.state(root)
        ran, log = self.run_on(root, JOIN, KEY, "tailscale")
        self.assertEqual(ran.returncode, 2, ran.stdout + ran.stderr)
        self.assertIn("Debian and Ubuntu", ran.stderr)
        self.assertEqual((log, self.state(root)), ([], before))

    def test_a_download_cut_short_anywhere_runs_nothing(self):
        lines = JOIN.splitlines(keepends=True)
        cuts = [len("".join(lines[:n])) for n in range(len(lines))]
        cuts += range(cuts[-1], len(JOIN) - 1)     # within the last line, the call
        root = self.machine()
        before = self.state(root)
        for cut in cuts:
            ran, log = self.run_on(root, JOIN[:cut], KEY, "tailscale")
            self.assertEqual((log, self.state(root)), ([], before), JOIN[:cut][-60:])

    def test_a_rented_machine_runs_todays_commands_in_todays_order(self):
        offer = google_cloud.Offer("c4a-standard-8", "europe-west4", 8, 32768, 0.4,
                                   image="debian-13-arm64", disk="hyperdisk-balanced")
        made = google_cloud._machine("acme-1", "europe-west4-a", offer, 3600, KEY)
        startup = next(item["value"] for item in made["metadata"]["items"]
                       if item["key"] == "startup-script")
        (today, then), (now, log) = [(root, self.run_on(root, script)) for root, script in
                                     [(self.machine(), TODAY), (self.machine(), startup)]]
        for ran, _ in (then, log):
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        rest = iter(log[1])
        self.assertEqual([one for one in then[1] if one not in rest], [])
        self.assertEqual(self.state(now), self.state(today))


if __name__ == "__main__":
    unittest.main()
