"""Probe a seat to prove ak's longest line is sent and its turn reads as working.

    python3 tests/probe_seat.py NAME [--wait SECONDS]

Reads and types only through `watch` (`screen_state`, `composer_draft`, `type_checked`), looking
in order for: (1) `at_prompt` with an empty composer, (2) `watch.type_checked` returning True for
one line of `watch.longest()` characters asking for a foreground `sleep 20` and a one-word reply,
(3) `working`, and (4) `at_prompt` with an empty composer again. Exits 0 if all four are seen in
order, else 1 naming on stderr the first unmet step and the last rows of the screen as ak read them.
"""

import argparse
from pathlib import Path
import re
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, watch  # noqa: E402

POLL = 0.2
ERRORS = (config.Error, OSError, ValueError, TypeError, KeyError, re.error)
HEADS = ("Run sleep 20 in the foreground, then reply with one word: OK.",
         "Run sleep 20 in the foreground, then reply OK.",
         "Run foreground sleep 20, reply OK.")


def whole_seconds(value):
    try:
        seconds = int(value)
    except ValueError:
        seconds = -1
    if seconds < 0:
        raise argparse.ArgumentTypeError(f"must be whole non-negative seconds: {value!r}")
    return seconds


def probe_line(length):
    """One printable ASCII line of `length` chars asking for foreground `sleep 20` then `OK`."""
    head = next((text for text in HEADS if length >= len(text)), HEADS[-1])
    if length <= len(head):
        return head[:length]
    note = " Ignore this padding:"
    if length >= len(head) + len(note) + 1:
        head += note
    pad, rest = " padding", length - len(head) - 1
    # End on a non-space so no composer trims the tail before type_checked compares it.
    return head + (pad * (rest // len(pad) + 1))[:rest] + "."


def wait_for(seconds, check, read_pane):
    """Poll `read_pane(timeout)` for at most `seconds` until `check(pane)` holds."""
    if seconds == 0:
        pane = read_pane(None)
        return check(pane), pane
    deadline, last = time.monotonic() + seconds, ""
    while (budget := deadline - time.monotonic()) > 0:
        pane = read_pane(min(orch.TMUX_CEILING, budget))
        last = pane or last
        remaining = deadline - time.monotonic()
        if remaining < 0:
            return False, last
        if check(pane):
            return True, last
        if remaining == 0:
            return False, last
        time.sleep(min(POLL, remaining))
    return False, last


def fail(step, reason, pane="", notes=()):
    tail = watch.strip_sgr(watch.pane_tail(pane)) if pane else ""
    print("\n".join([f"step {step}: {reason}", *notes, *([tail] if tail else ())]), file=sys.stderr)
    return 1


def probe(name, wait):
    try:
        session = orch.find(name)
        if session is None:
            return fail(1, f"seat {name!r} not found")
        session = watch.pinned(session)
    except ERRORS as exc:
        return fail(1, str(exc))

    seen = [""]

    def read_pane(timeout=None):
        try:
            pane = (watch.pane_text(session) if timeout is None
                    else watch.pane_text(session, timeout=timeout))
        except OSError:
            return ""
        seen[0] = pane or seen[0]
        return pane

    try:
        harness, _ = watch.seat_model(config.load(), session["name"])
    except ERRORS as exc:
        return fail(1, str(exc), read_pane() or seen[0])
    if not harness:
        return fail(1, f"seat {session['name']!r} has no configured harness", read_pane() or seen[0])

    def at_empty(pane):
        return (watch.screen_state(harness, pane)[0] == "at_prompt"
                and watch.composer_draft(harness, pane) == "")

    def wait_step(step, check, label):
        try:
            ok, pane = wait_for(wait, check, read_pane)
            if ok:
                return None
            pane = pane or seen[0]
            state, rule, _ = watch.screen_state(harness, pane)
            draft = watch.composer_draft(harness, pane)
        except ERRORS as exc:
            return fail(step, str(exc), seen[0] or read_pane())
        shown = draft[:60] + "..." if isinstance(draft, str) and len(draft) > 60 else draft
        return fail(step, f"did not read {label} (state={state!r}, rule={rule!r}, draft={shown!r})", pane)

    if (code := wait_step(1, at_empty, "at_prompt with an empty composer")) is not None:
        return code

    logs = []
    try:
        sent = watch.type_checked(session, probe_line(watch.longest()), logs.append, harness=harness)
    except ERRORS as exc:
        return fail(2, str(exc), read_pane() or seen[0], logs)
    if sent is not True:
        return fail(2, f"type_checked returned {sent!r}", read_pane() or seen[0], logs)

    code = wait_step(3, lambda p: watch.screen_state(harness, p)[0] == "working", "working")
    return code if code is not None else (wait_step(4, at_empty, "at_prompt with an empty composer again") or 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Probe a seat through watch.")
    parser.add_argument("name", help="seat name")
    parser.add_argument("--wait", type=whole_seconds, default=120, metavar="SECONDS")
    args = parser.parse_args(argv)
    return probe(args.name, args.wait)


if __name__ == "__main__":
    sys.exit(main())
