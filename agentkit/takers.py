"""The machines that take over from this client's home, as the home named them at the end of the
last menu it served (`ak standby --takers`): kept in ak's tmp folder, one name a line, and
believed only whole, every line a name by `standby.HOST`, so no line of it reaches ssh as an
option.  `menu.client_menu` keeps the list and tries its names once the home does not answer.
"""

import os
import re

from . import config, standby

# each name ending its line or the list
WHOLE = re.compile(f"(?:{standby.HOST}(?:\n|\\Z))*".encode())


def read():
    """The names kept, in the list's order: none where it is not there, cannot be read, or holds
    any other line."""
    try:
        held = config.read_regular(config.TMP / "takers")
    except OSError:
        return []
    return held.decode().split() if WHOLE.fullmatch(held) else []


def write(printed):
    """Replace the list whole by `printed`, the home's answer, where each line of it is a name,
    none among them: through a file of this process's own beside it, renamed onto it, so a
    reader never sees half of one.  Any other answer leaves the list as it was."""
    if WHOLE.fullmatch(printed):
        config.TMP.mkdir(mode=0o700, exist_ok=True)     # ak's folder is there: it names the home
        own = config.TMP / f"takers.{os.getpid()}"
        own.write_bytes(printed)
        own.replace(config.TMP / "takers")
