package tick

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/launch"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

const (
	deadBackoff = 600  // a loop that dies again this soon after its resume waits this long
	deadWindow  = 3600 // a third death inside this parks the run and tells the seat once
)

// deadLoops is watch.resume_dead_loops: a live record whose loop process is gone has its death
// recorded and goes on in the same tick, through Go's own resume, so nobody is asked.  A death
// within ten minutes of that resume waits them out, and a third inside an hour parks the run, the
// recovery notice saying so once.  Nothing is written for a run Go does not carry.
func (t *ticking) deadLoops() error {
	var failed error
	carried := run.Every(func(dir string, record *run.Object) bool {
		now, id, wt := epoch(t.clock()), filepath.Base(dir), record.Str("worktree")
		change := func(edit func(*run.Object)) bool {
			failed = run.Change(dir, func(current *run.Object) error {
				if !run.Equal(current, record) {
					return errMovedRun
				}
				edit(current)
				return nil
			})
			return failed == nil
		}
		switch {
		case !deadLoop(record, now):
			return true
		case scoped(record):
			return false // Python asks the unit whether its memory cap ended the loop, and stops it
		case wt == "" && !(record.Str("state") == "queued" && record.Truthy("slot_waiting")):
			return true // nothing to continue into: reap's to hand back
		case wt != "" && !directory(wt):
			if record.Truthy("dead_worktree_warned") {
				return true
			}
			if !change(func(current *run.Object) { current.Set("dead_worktree_warned", now) }) {
				return false
			}
			t.log.line(fmt.Sprintf("WARN %s: worktree %s is gone; leaving it for an explicit resume", id, wt))
			return true
		}
		action, deaths, reason := deadPlan(record, now)
		role, rnd := deadWhere(dir, record)
		var edit func(*run.Object)
		var line string
		switch action {
		case "skip":
			return true
		case "wait":
			// reap reads `resume_after` and leaves the dead pid alone until it passes
			edit = func(current *run.Object) { holdLive(current, deaths).Set("resume_after", backoffUntil(deaths)) }
			line = fmt.Sprintf("waiting to resume %s: loop died (%s); next try after 10 min", id, reason)
		case "park":
			if run.Launched(record) != "" && !seat.Watching(run.Seat(record)) {
				return false // a notice for a seat that cannot take it now is Python's
			}
			edit = func(current *run.Object) {
				host.EndMarked(dir, io.Discard) // what the dead loop left running, which reap ends once per loop
				run.SetAll(current, "state", "interrupted", "interrupted_at", now, "interruption_reason", reason,
					"recovery_pending", true, "deaths", deaths, "tree_stopped", []any{current.Get("pid"), current.Get("process_identity")})
				current.Delete("resume_after")
			}
			line = fmt.Sprintf("parked %s: loop died (%s); third death within an hour", id, reason)
		default:
			last := deaths[len(deaths)-1].(*run.Object).Copy()
			last.Set("resumed_at", now)
			deaths[len(deaths)-1] = last
			// the order the resume adopts the record by, as Python's resume and reap read it
			edit = func(current *run.Object) {
				holdLive(current, deaths).Delete("resume_after")
				run.SetAll(current, "stall_resume_at", now, "resume_notice", run.Fields("at", now, "role", role, "restarted", false))
			}
			line = fmt.Sprintf("resumed %s: loop died (%s); continuing %s of round %d", id, reason, role, rnd)
		}
		note := func() { run.Note(dir, line, t.clock()) }
		if action == "resume" {
			// the order lands with the resume's own write, so one Go leaves to Python leaves nothing,
			// and its note before the driver starts, so the driver's own lines follow it
			code, why, err := launch.ResumeExpected(id, record, edit, note)
			switch {
			case errors.Is(err, launch.ErrPython):
				return false
			case err != nil || code != 0:
				t.log.line(fmt.Sprintf("WARN could not resume %s: %s", id, cmp.Or(why, fmt.Sprint(err))))
				return true
			}
		} else if !change(edit) {
			return false
		} else {
			note()
		}
		t.log.line(line)
		if action == "park" {
			failed = loop.OfferEnding(dir, t.log.line)
			return failed == nil
		}
		return true
	})
	if !carried {
		if errors.Is(failed, errMovedRun) {
			return errLeft
		}
		return cmp.Or(failed, errLeft)
	}
	return nil
}

// deadLoop is whether the pass looks at that record: a live one, or one a reap found dead first,
// that nobody stopped, its last death not parked, past its launch's grace and its process gone.
func deadLoop(record *run.Object, now float64) bool {
	deaths := record.List("deaths")
	if !run.Active(record) && !(record.Str("state") == "interrupted" && len(deaths) > 0) {
		return false
	}
	if len(deaths) > 0 {
		if last, ok := deaths[len(deaths)-1].(*run.Object); ok && last.Truthy("parked") {
			return false
		}
	}
	return !run.LaunchGrace(record, now) && !run.ProcessActive(record)
}

// scoped is whether a unit the manager holds ran that loop (turns.scope_is_real).
func scoped(record *run.Object) bool {
	scope := record.Str("scope")
	return scope != "" && !strings.HasPrefix(scope, "none")
}

// deadPlan is _dead_plan: what the tick does with a loop whose process is gone, the deaths it
// leaves on the record and why.  `skip` is a resume already ordered or a backoff a reap's death
// is still in, `wait` records a death and holds for the backoff, `park` is the third death
// inside an hour, and `resume` continues now.
func deadPlan(record *run.Object, now float64) (string, []any, string) {
	var deaths []any
	for _, death := range record.List("deaths") {
		if _, ok := death.(*run.Object); ok {
			deaths = append(deaths, death)
		}
	}
	// a resume already ordered adopts the record itself: noticing the dead pid again would
	// launch a second loop
	if run.ResumeOrdered(record, now) {
		return "skip", nil, ""
	}
	last := run.NewObject()
	if len(deaths) > 0 {
		last = deaths[len(deaths)-1].(*run.Object)
	}
	reaped := len(deaths) > 0 && run.Equal(last.Get("pid"), record.Get("pid")) && !last.Truthy("parked") && !last.Truthy("resumed_at")
	// the hour runs to the death being judged, not to the tick judging it
	upto := now
	if at, ok := dated(last, "at"); reaped && ok {
		upto = at
	}
	recent := 0
	for _, death := range deaths {
		if at, ok := dated(death.(*run.Object), "at"); ok && upto-at < deadWindow {
			recent++
		}
	}
	if reaped {
		// a reap noticed this death first and recorded it, so it is among the recent already
		switch {
		case recent >= 3:
			parked := last.Copy()
			parked.Set("parked", true)
			return "park", append(deaths[:len(deaths)-1], parked), last.Str("reason")
		case now < backoffUntil(deaths):
			return "skip", nil, ""
		}
		return "resume", deaths, last.Str("reason")
	}
	noticed := time.Unix(0, int64(now*1e9)).Format("2006-01-02 15:04:05")
	reason := fmt.Sprintf("loop process %s gone, noticed %s", run.Field(record, "pid", "None"), noticed)
	entry := run.Fields("at", now, "pid", record.Get("pid"), "reason", reason)
	if recent >= 2 {
		entry.Set("parked", true)
		return "park", append(deaths, entry), reason
	}
	if previous, ok := dated(last, "resumed_at"); ok && now-previous < deadBackoff {
		return "wait", append(deaths, entry), reason
	}
	return "resume", append(deaths, entry), reason
}

// backoffUntil is when the backoff after the latest resume ends, 0 with none.
func backoffUntil(deaths []any) float64 {
	for at := len(deaths) - 1; at >= 0; at-- {
		if resumed, ok := dated(deaths[at].(*run.Object), "resumed_at"); ok {
			return resumed + deadBackoff
		}
	}
	return 0
}

// holdLive records the deaths and keeps the record live: a death the tick answers itself is not
// interrupted work, nor one a person is told of.  A queued slot keeps its `queued_at`.
func holdLive(record *run.Object, deaths []any) *run.Object {
	record.Set("state", "running")
	if record.Truthy("slot_waiting") {
		record.Set("state", "queued")
	}
	for _, key := range []string{"recovery_pending", "recovery_notified", "interrupted_at", "interruption_reason"} {
		record.Delete(key)
	}
	record.Set("deaths", deaths)
	return record
}

// deadWhere is the role and round a dead loop was in: the last round anything ran in, its
// directory the record of it (staffing.started_round), else the first.
func deadWhere(dir string, record *run.Object) (string, int) {
	role := cmp.Or(record.Str("step"), "executor")
	if record.Str("state") == "queued" && record.Truthy("slot_waiting") {
		role = "slot wait"
	}
	rnd := len(record.List("round_summaries"))
	entries, _ := os.ReadDir(dir)
	for _, entry := range entries {
		number, numbered := strings.CutPrefix(entry.Name(), "round-")
		if n, err := strconv.Atoi(number); numbered && err == nil && strings.Trim(number, "0123456789") == "" {
			rnd = max(rnd, n)
		}
	}
	return role, max(rnd, 1)
}
