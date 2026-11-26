"""install.sh run from outside in an answer-key Home, as a person runs it on a new machine.

install.sh is at the root of the checkout whose `bin/` holds the program `AK_BIN` names, so the
build under test installs itself, and `run(home, *args)` runs it with no terminal.  `prepare`
puts first on its PATH a refusing, logging fake of each tool install.sh sets a host up with
(sudo, apt-get, dpkg, brew, npm, launchctl), beside the Home's own, and a `hostname`
that names no server, so no install reaches the machine's packages, tailnet or launch agents.

To install.sh a HOME that is not the account's own is a sandbox, where nothing outside it is
touched.  `own_home` makes the Home the account's own as `id` names it, with an `npm` that
takes its settings and a `crontab` keeping its table in `<root>/crontab`, so a server install
does all it does on a real host, every tool it calls a fake.  `without` takes programs off the
Home's PATH, the host's copies too.

    from fixtures.akbin import Home
    from fixtures import installer
    with Home() as home:
        installer.prepare(home)
        done = installer.run(home, "--client", "acme-box")
        assert (home.path / ".agentkit/state/server").read_text() == "acme-box\n"
"""

import os
from pathlib import Path
import re
import shlex
import shutil

from .akbin import AK
from .akinstall import PROGRAM, copy_tracked

CHECKOUT = Path(AK).parents[1]
INSTALL = CHECKOUT / "install.sh"
HOST = ("sudo", "apt-get", "dpkg", "brew", "npm", "launchctl")
# An empty name for the account: install.sh then reads the account's home as `~`, its HOME.
ID = '#!/bin/sh\n[ "$1" = -un ] && exit 0\nexec /usr/bin/id "$@"\n'
CRONTAB = """#!/bin/sh
case "$1" in
  -l) [ -f {table} ] || {{ echo "no crontab for acme" >&2; exit 1; }}; exec cat {table} ;;
  -) exec cat >{table} ;;
esac
exit 1
"""


def prepare(home):
    for name in HOST:
        home.refuse(name)
    home.fake("hostname", "#!/bin/sh\necho acme-host\n")


def own_home(home):
    """The Home is the account's own from now on; the crontab's table is `<root>/crontab`."""
    home.fake("id", ID)
    home.fake("npm", "#!/bin/sh\nexit 0\n")
    # where its commands find it: a machine's of tests/fixtures/twohomes.py too
    home.fake("crontab", CRONTAB.format(table=shlex.quote(str(home.at / "crontab"))))
    home.env.update(USER="", LOGNAME="")


def without(home, *names):
    """No program `names` is on the Home's PATH from now on, whatever the host has: its own `bin`
    loses them, and the host directories after it are one of links to every other program on
    them, the first that runs, as a PATH lookup finds it, so an install still runs every host
    tool but these."""
    tools = home.root / "tools"
    tools.mkdir()
    for name in names:
        (home.bin / name).unlink(missing_ok=True)
    for folder in home.env["PATH"].split(os.pathsep):
        if folder != str(home.at / "bin") and os.path.isdir(folder):
            for tool in Path(folder).iterdir():
                if (tool.name not in names and not os.path.lexists(tools / tool.name)
                        and tool.is_file() and os.access(tool, os.X_OK)):
                    (tools / tool.name).symlink_to(tool)
    home.env["PATH"] = os.pathsep.join([str(home.at / "bin"), str(tools)])


def copy(to):
    """A copy of the checkout `AK_BIN` names, its tests aside, with its program; its install.sh."""
    copy_tracked(to)
    program = to / Path(AK).resolve().relative_to(PROGRAM)
    program.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(AK, program)
    return to / INSTALL.resolve().relative_to(PROGRAM)


def run(home, *args):
    return home.run("bash", str(INSTALL), *args)


def cron(row):
    """A crontab `row`'s schedule, its first five fields, then what cron hands sh of the rest and
    the input it gives that, as cron reads them: the fields parted by spaces and tabs; in the
    command a backslash and the next character a pair, \\% a %, and the first other % its end; in
    the input after that % a \\% a %, each other % a newline, and one more at its end where
    its last character but backslashes is not one."""
    *schedule, rest = re.split(r"[ \t]+", row.lstrip(" \t"), 5)
    command, given = re.fullmatch(r"((?:\\.|[^\\%])*\\?)(?:%(.*))?", rest, re.S).groups()
    given = re.sub(r"\\?%", lambda found: "%" if found[0] == "\\%" else "\n", given or "")
    return (schedule, re.sub(r"\\(.)", lambda pair: "%" if pair[1] == "%" else pair[0], command,
                             flags=re.S),
            given + "\n" if given.rstrip("\\")[-1:] not in ("", "\n") else given)
