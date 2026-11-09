// Package handback gives a seat's run its ending back, as Python's handback.announce and hand_back
// do: an ending in, told or left pending out (Give).  It hides the delivery lock the ending is said
// once under, the marks Python's tick and screens read (`handed_back`, `handback_pending`,
// `handback_typed`, as mark_delivery writes them), the one line the seat is told in, and the send
// that types it at the seat's quiet prompt (seat.TypeAtPrompt).
//
// Go hands back as Python's hand_back does, to a seat up on ak's own server, a sleeping one woken
// for an ending typed into it; an ending it does not type is marked pending, which the tick offers
// at the next quiet prompt: a seat that takes no line now, or a line whose compact form cannot fit.
// A seat nothing is left of has its ending reported to the owner (Orphaned), and a job's task's,
// gone, its job's one line (muted); any other seat not up there is still Python's to wake, reopen
// or wait for.
package handback

import (
	"context"
	"fmt"
	"path/filepath"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

const (
	maxAge       = 3600 // an ending older than this when first seen is history (watch.HANDBACK_MAX_AGE)
	preexisting  = "pre-existing ending; not replayed"
	routine      = "routine ending: recorded, not typed"
	decisionMost = 399 // one read tells a seat what it decides (handback.DECISION_MOST)
)

// Give hands the ending of the run at dir back to the seat that launched it, saying in the run's
// log what came of it; true where the seat has been told, now or before.  Its seat's other runs
// are read from census, the pass's one read of every run, else as they stand; its own is read
// again under the delivery lock.
func Give(dir string, census []*run.Object, say func(string)) bool {
	record, _ := run.Read(dir)
	if record == nil {
		return false
	}
	session, id := run.Seat(record), filepath.Base(dir)
	if session == "" || !run.Ended(record) && !recoveryEnding(record) || record.Str("state") == "stopped" ||
		record.Str("state") == "error" && run.Going(record, time.Now()) || !Reaches(record) {
		return false
	}
	gone := !seat.Watching(session)
	if gone && !Orphaned(record) && !muted(record) {
		awake, carried := seat.Wake(session, say)
		if carried && !awake {
			mark(dir, record, "handback_pending", true) // owed: what next wakes it hands it back
		}
		if !awake {
			return false
		}
		gone = false
	}
	held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return false
	}
	defer held.Close()
	said, _ := run.Read(dir)
	switch {
	case said == nil || !sameAttempt(record, said):
		// resumed since this ending: the attempt running now hands back an ending of its own
		say(fmt.Sprintf("run %s has moved on since this ending; nothing to hand back", id))
		return false
	case handedBack(said):
		say(fmt.Sprintf("run %s was already handed back to the %s seat", id, session))
		return true
	case run.Ended(said) && !said.Truthy("handback_pending") && !said.Truthy("notification_pending") && history(said):
		mark(dir, record, "handed_back", now(), "handback_note", preexisting, "handback_pending", nil,
			"handback_wait_reason", nil, "notification_pending", nil)
		say(fmt.Sprintf("run %s is a %s", id, preexisting))
		return true
	}
	if gone {
		if Orphaned(said) {
			orphan(dir, said, session, id, say)
		} else if muted(said) {
			mark(dir, record, "reported", true, "handback_pending", nil) // its job's line says it
		}
		return false // the seat was told nothing
	}
	recordOnly, pending := seat.EndingDelivery(said, census, session)
	if recordOnly {
		if !mark(dir, record, "handed_back", now(), "reported", true, "handback_note", routine,
			"handback_pending", nil, "handback_typed", nil, "handback_wait_reason", nil, "notification_pending", nil) {
			return false
		}
		say(fmt.Sprintf("run %s ended: recorded, not typed", id))
		return true
	}
	holds, live, err := liveEnding(said)
	if err != nil {
		return false // Python's to read, as the tick leaves it (Reaches)
	}
	if holds {
		if !said.Truthy("handback_pending") {
			mark(dir, record, "handback_pending", true)
		}
		return false // told in one line with its change gone live, once it is
	}
	// a mark an earlier pass left is a line already in the composer, whose Enter is the tick's
	line := ""
	if !pending {
		line = handbackLine(record, dir, true, live)
	}
	if line != "" && !said.Truthy("handback_typed") && seat.TypeAtPrompt(session, line, nil, func(typed *run.Object) error {
		mark(dir, record, append([]any{"handback_typed", typed}, saidLive(live, "live_typed", typed)...)...)
		return nil
	}, say) {
		Told(dir, record, saidLive(live, "live_notified", now(), "live_typed", nil)...)
		say(fmt.Sprintf("handed run %s back to the %s seat", id, session))
		return true
	}
	first := !said.Truthy("handback_pending") || record.Truthy("handed_back")
	if first {
		// an ending is said or waiting to be, never both: an earlier attempt's mark goes with it
		mark(dir, record, "handback_pending", true, "handed_back", nil, "handback_note", nil)
	}
	if reading, atPrompt := seat.Untyped(session); first || atPrompt {
		say(fmt.Sprintf("the %s seat is not at its prompt (%s); the tick hands run %s back", session, reading, id))
	}
	return false
}

// Told marks the run's ending told to the seat, as its hand-back and the NOT LIVE line of its
// merge typed into the seat that launched it do, with any more marks; false where the record moved
// on.
func Told(dir string, record *run.Object, more ...any) bool {
	return mark(dir, record, append([]any{"handed_back", now(), "reported", true, "handback_pending", nil, "handback_typed", nil,
		"handback_note", nil, "handback_wait_reason", nil, "notification_pending", nil}, more...)...)
}

// saidLive is the marks of a line that says its change went live too, none for one that does not.
func saidLive(live bool, marks ...any) []any {
	if live {
		return marks
	}
	return nil
}

// sameAttempt is whether two records are one attempt of the run, not either side of a resume.
func sameAttempt(a, b *run.Object) bool {
	for _, key := range []string{"pid", "finished_at", "interrupted_at"} {
		if !run.Equal(a.Get(key), b.Get(key)) {
			return false
		}
	}
	return true
}

// handedBack is whether this ending, and not an earlier attempt's, was handed back: an undated
// mark is taken at its word.
func handedBack(record *run.Object) bool {
	return run.HandedBack(record)
}

// history is an ending older than an hour, or with no date to age by but a start that is: never
// replayed (watch.is_preexisting).
func history(record *run.Object) bool {
	for _, key := range []string{"finished_at", "interrupted_at"} {
		if at, ok := run.Num(record.Get(key)); ok {
			return seconds()-at > maxAge
		}
	}
	started, ok := run.Num(record.Get("started_at"))
	return ok && seconds()-started > maxAge
}

// mark writes delivery marks onto the record as it stands, nil removing one, only while it is
// still the attempt `snapshot` is of, as Python's mark_delivery; the snapshot takes them too.
func mark(dir string, snapshot *run.Object, pairs ...any) bool {
	err := run.Deliver(dir, func(current *run.Object) error {
		if !sameAttempt(snapshot, current) {
			return errMoved
		}
		marked(current, pairs)
		return nil
	})
	if err != nil {
		return false
	}
	marked(snapshot, pairs)
	return true
}

// marked puts the marks on a record, nil removing one.
func marked(record *run.Object, pairs []any) {
	for at := 0; at < len(pairs); at += 2 {
		if key := pairs[at].(string); pairs[at+1] == nil {
			record.Delete(key)
		} else {
			record.Set(key, pairs[at+1])
		}
	}
}

var errMoved = fmt.Errorf("the run moved on")

func seconds() float64 { return float64(time.Now().UnixNano()) / 1e9 }

func now() run.Number { return run.Float(seconds()) }
