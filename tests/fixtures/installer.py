"""install.sh run from outside in an answer-key Home, as a person runs it on a new machine.

install.sh is at the root of the checkout whose `bin/` holds the program `AK_BIN` names, so the
build under test installs itself, and `run(home, *args)` runs it with no terminal.  `prepare`
puts first on its PATH a refusing, logging fake of each tool install.sh sets a host up with
(sudo, apt-get, dpkg, brew, npm, launchctl), beside the Home's own, and a `hostname`
that names no server, so no install reaches the machine's packages, tailnet or launch agents.

To install.sh a HOME that is not the account's own is a sandbox, where nothing outside it is
touched.  `own_home` makes the Home the account's own as `id` names it, with an `npm` that
takes its settings and a `crontab` keeping its table in `<root>/crontab`, so a server install
does all it does on a real host, every tool it calls a fake.

    from fixtures.akbin import Home
    from fixtures import installer
    with Home() as home:
        installer.prepare(home)
        done = installer.run(home, "--client", "acme-box")
        assert (home.path / ".agentkit/state/server").read_text() == "acme-box\n"
"""

from pathlib import Path
import re
import shlex

from .akbin import AK

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


def run(home, *args):
    return home.run("bash", str(INSTALL), *args)


def cron(row):
    """A crontab `row`'s schedule, its first five fields, then what cron hands sh of the rest and
    the input it gives that, as cron's do_command reads them: in the command a backslash and the
    next character are a pair, \\% a %, and the first other % ends it; in the input after that % a
    \\% is a % and each other % a newline."""
    *schedule, rest = row.split(None, 5)
    command, given = re.fullmatch(r"((?:\\.|[^\\%])*\\?)(?:%(.*))?", rest, re.S).groups()
    return (schedule, re.sub(r"\\(.)", lambda pair: "%" if pair[1] == "%" else pair[0], command,
                             flags=re.S),
            re.sub(r"\\?%", lambda found: "%" if found[0] == "\\%" else "\n", given or ""))
