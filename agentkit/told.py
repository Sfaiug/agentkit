"""What a line one seat sends another with `ak tell` starts with, and how a prompt is known as one.

The heading's one home, and that of ak's own notice that asks nothing: agentkit/tell.py writes the
first, the tick's line saying a run is live the second, and hooks/seat-state.sh asks `told` whether
a prompt starts with either whole.  Nothing here imports the rest of agentkit, so the hook's
question costs no more than Python's start.
"""

import re
import time

HEADING = "[from seat {sender} at {at}, not the owner; reply with ak tell {sender}] "
# A seat that declared done before such a notice has nothing new to declare after it.
NOTICE = "[from ak, not the owner] "

_SENDER = re.escape("{sender}")
_TOLD = re.compile(r"\s*(?:" + re.escape(HEADING).replace(_SENDER, r"(?P<sender>.+)", 1)
                   .replace(_SENDER, r"(?P=sender)").replace(re.escape("{at}"), r"\d\d:\d\d")
                   + "|" + re.escape(NOTICE) + ")")


def heading(sender, now):
    """The heading of a line `sender` told at `now`: who sent it, and that it is not the owner's."""
    return HEADING.format(sender=sender, at=time.strftime("%H:%M", time.localtime(now)))


def told(text):
    """Does that prompt start with a whole heading, as only `ak tell` and ak's notice write one?"""
    return isinstance(text, str) and _TOLD.match(text) is not None
