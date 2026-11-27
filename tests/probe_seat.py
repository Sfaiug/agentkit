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
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, watch  # noqa: E402

POLL = 0.2


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
    core = "Run sleep 20 in the foreground, then reply with one word: OK."
    head = core if length >= len(core) else "Run sleep 20 in the foreground, then reply OK."
    if length <= len(head):
        return head[:length]
    note = " Ignore this padding:"
    if length >= len(head) + len(note) + 1:
        head += note
    pad, rest = " padding", length - len(head) - 1
    # End on a non-space so no composer trims the tail before type_checked compares it.
    return head + (pad * (rest // len(pad) + 1))[:rest] + "."


def wait_for(seconds, check, read_pane):
    """Poll `read_pane()` for at most `seconds` until `check(pane)` holds; return (ok, pane)."""
    deadline = time.monotonic() + seconds
    pane = ""
    while True:
        pane = read_pane()
        remaining = deadline - time.monotonic()
        if remaining < 0:
            return False, pane
        if check(pane):
            return True, pane
        if remaining == 0:
            return False, pane
        time.sleep(min(POLL, remaining))
        if time.monotonic() > deadline:
            return False, pane


def at_empty_prompt(harness, pane):
    return (watch.screen_state(harness, pane)[0] == "at_prompt"
            and watch.composer_draft(harness, pane) == "")


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
    except (config.Error, OSError) as exc:
        return fail(1, str(exc))

    def read_pane():
        try:
            return watch.pane_text(session)
        except OSError:
            return ""

    try:
        harness, _ = watch.seat_model(config.load(), session["name"])
    except (config.Error, OSError) as exc:
        return fail(1, str(exc), read_pane())
    if not harness:
        return fail(1, f"seat {session['name']!r} has no configured harness", read_pane())

    def wait_step(step, check, label):
        try:
            ok, pane = wait_for(wait, check, read_pane)
            if ok:
                return None
            state, rule, _ = watch.screen_state(harness, pane)
            draft = watch.composer_draft(harness, pane)
        except (config.Error, OSError) as exc:
            return fail(step, str(exc), read_pane())
        shown = draft[:60] + "..." if isinstance(draft, str) and len(draft) > 60 else draft
        return fail(step, f"did not read {label} (state={state!r}, rule={rule!r}, draft={shown!r})",
                    pane)

    if (code := wait_step(1, lambda p: at_empty_prompt(harness, p),
                          "at_prompt with an empty composer")) is not None:
        return code

    logs = []
    try:
        sent = watch.type_checked(session, probe_line(watch.longest()), logs.append, harness=harness)
    except (config.Error, OSError) as exc:
        return fail(2, str(exc), read_pane(), logs)
    if sent is not True:
        return fail(2, f"type_checked returned {sent!r}", read_pane(), logs)

    if (code := wait_step(3, lambda p: watch.screen_state(harness, p)[0] == "working",
                          "working")) is not None:
        return code
    return wait_step(4, lambda p: at_empty_prompt(harness, p),
                     "at_prompt with an empty composer again") or 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Probe a seat through watch.")
    parser.add_argument("name", help="seat name")
    parser.add_argument("--wait", type=whole_seconds, default=120, metavar="SECONDS")
    args = parser.parse_args(argv)
    return probe(args.name, args.wait)


if __name__ == "__main__":
    sys.exit(main())
