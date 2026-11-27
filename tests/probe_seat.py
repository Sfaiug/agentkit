"""Probe a seat to prove ak's longest line is sent and its turn reads as working.

    python3 tests/probe_seat.py NAME [--wait SECONDS]

Reads and types only through `watch` (`screen_state`, `composer_draft`, `type_checked`), looking
in order for:

1. the seat reading `at_prompt` with an empty composer;
2. `watch.type_checked` answering True for one line of `watch.longest()` characters asking for a
   foreground `sleep 20` and a one-word reply;
3. the seat reading `working`;
4. the seat reading `at_prompt` with an empty composer again.

Exits 0 when all four are seen in order; otherwise 1, naming on stderr the number of the first
step not seen and the last rows of the screen as ak read them.
"""

import argparse
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, watch  # noqa: E402

POLL = 0.2


def non_negative_int(value):
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a whole number of seconds: {value!r}") from None
    if seconds < 0:
        raise argparse.ArgumentTypeError(f"must be non-negative: {value!r}")
    return seconds


def probe_line(length):
    """One printable ASCII line of `length` characters asking for a foreground `sleep 20` and a
    one-word reply."""
    head = ("Run sleep 20 in the foreground, not in the background, then reply with only the word "
            "OK. Ignore the padding below; it only tests a full-length line:")
    if length <= len(head):
        return head[:length]
    pad = " padding"
    rest = length - len(head) - 1
    body = (pad * (rest // len(pad) + 1))[:rest]
    # End on a non-space so no composer trims the tail before type_checked compares it.
    return head + body + "."


def wait_for(seconds, check, read_pane):
    """Poll `read_pane()` up to `seconds` until `check(pane)` holds; return (ok, last_pane)."""
    deadline = time.monotonic() + seconds
    pane = ""
    while True:
        pane = read_pane()
        if check(pane):
            return True, pane
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, pane
        time.sleep(min(POLL, remaining))


def at_empty_prompt(harness, pane):
    return (watch.screen_state(harness, pane)[0] == "at_prompt"
            and watch.composer_draft(harness, pane) == "")


def preview(draft):
    if isinstance(draft, str) and len(draft) > 60:
        return draft[:60] + "..."
    return draft


def fail(step, reason, pane="", notes=()):
    print(f"step {step}: {reason}", file=sys.stderr)
    for note in notes:
        print(note, file=sys.stderr)
    tail = watch.strip_sgr(watch.pane_tail(pane)) if pane else ""
    if tail:
        print(tail, file=sys.stderr)
    return 1


def probe(name, wait):
    cfg = config.load()
    session = orch.find(name)
    if session is None:
        return fail(1, f"seat {name!r} not found")
    session = watch.pinned(session)

    def read_pane():
        return watch.pane_text(session)

    harness, _ = watch.seat_model(cfg, session["name"])
    if not harness:
        return fail(1, f"seat {session['name']!r} has no configured harness", read_pane())

    ok, pane = wait_for(wait, lambda p: at_empty_prompt(harness, p), read_pane)
    if not ok:
        state, rule, _ = watch.screen_state(harness, pane)
        draft = watch.composer_draft(harness, pane)
        return fail(1, f"did not read at_prompt with an empty composer "
                       f"(state={state!r}, rule={rule!r}, draft={preview(draft)!r})", pane)

    logs = []
    sent = watch.type_checked(session, probe_line(watch.longest()), logs.append, harness=harness)
    if sent is not True:
        return fail(2, f"type_checked returned {sent!r}", read_pane(), logs)

    ok, pane = wait_for(wait, lambda p: watch.screen_state(harness, p)[0] == "working", read_pane)
    if not ok:
        state, rule, _ = watch.screen_state(harness, pane)
        return fail(3, f"did not read working (state={state!r}, rule={rule!r})", pane)

    ok, pane = wait_for(wait, lambda p: at_empty_prompt(harness, p), read_pane)
    if not ok:
        state, rule, _ = watch.screen_state(harness, pane)
        draft = watch.composer_draft(harness, pane)
        return fail(4, f"did not read at_prompt with an empty composer again "
                       f"(state={state!r}, rule={rule!r}, draft={preview(draft)!r})", pane)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Probe a seat through watch to confirm ak's longest line is sent and runs.")
    parser.add_argument("name", help="seat name")
    parser.add_argument("--wait", type=non_negative_int, default=120, metavar="SECONDS",
                        help="whole seconds to poll each wait step (default: 120)")
    args = parser.parse_args(argv)
    return probe(args.name, args.wait)


if __name__ == "__main__":
    sys.exit(main())
