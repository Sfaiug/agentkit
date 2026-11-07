package launch

import (
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strconv"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/machines"
	"agentkit/internal/run"
)

// gated is whether Python's gate decides this process's launch: its claim_slot lets a run's own
// run in outright, and every run under the tests' `AK_MAX_RUNS=0`.
func gated() bool {
	depth, _ := runDepth()
	_, capped := config.MaxRuns()
	return capped == nil && os.Getenv("AK_MAX_RUNS") != "0" && depth == 0
}

// An admission is the slot Python's gate would let a launch into at its first poll, held under
// the slots lock from that decision until the launch's receipt claims it or the launch goes.
type admission struct {
	slots   *os.File
	running int   // the other runs holding a slot
	took    []any // the queue's waits first in line of the last runs let in
}

// admit decides the launch's admission under the slots lock as Python's claim_slot would at its
// first poll, none for a launch no gate decides.  It is ErrPython wherever that poll would hold the
// run, and wherever Go would judge it otherwise: history.db standing, whose peaks Python counts
// against memory; readings of the live host rather than AK_HOST_READINGS; another run waiting for
// a slot; a queue, a poll or a run Go reads otherwise than Python.
func admit(first bool) (*admission, error) {
	if !gated() {
		return nil, nil
	}
	if err := os.MkdirAll(run.Runs(), 0o777); err != nil {
		return nil, err
	}
	slots, err := holdSlots()
	if err != nil {
		return nil, err
	}
	if admitted, ok := letIn(first); ok {
		admitted.slots = slots
		return admitted, nil
	}
	slots.Close()
	return nil, ErrPython
}

// letIn is the admission Python's gate gives the launch now, false where Go leaves it to Python.
func letIn(first bool) (*admission, bool) {
	if !run.Historyless() {
		return nil, false
	}
	_, took, lastIn, read := queued()
	poll, polled := slotPoll()
	readings, injected := host.Injected()
	limit, err := config.MaxRuns()
	if !read || !polled || !injected || err != nil {
		return nil, false
	}
	holders, alone := holding()
	if !alone || limit > 0 && len(holders) >= limit && !first {
		return nil, false
	}
	// finished work goes first: a line's check waiting for a heavy-suite turn holds a new run,
	// unless ak has another machine for that suite (owner, 30 Oct 2026: nothing waits for compute)
	if !first && host.LineCheckWaits() && len(machines.Known()) == 1 {
		return nil, false
	}
	// with no peak measured, a run waits a poll after the last one let in, for steady readings
	if since := now() - lastIn; 0 <= since && since < poll {
		return nil, false
	}
	admits, err := host.Admits(readings, first, func() int {
		return len(slices.DeleteFunc(slices.Clone(holders), func(pid int) bool { return !host.Frozen(pid) }))
	})
	return &admission{running: len(holders), took: took}, admits && err == nil
}

// holding is the pids of the other top-level runs holding a slot, as Python's slot_counts counts
// them, false where one waits for a slot, a dead waiter among them, or the runs cannot be read.
func holding() ([]int, bool) {
	var pids []int
	alone := run.Every(func(_ string, other *run.Object) bool {
		switch {
		case other.Truthy("run_depth"):
		case other.Str("state") == "running" && run.ProcessActive(other):
			pid, _ := other.Int("pid")
			pids = append(pids, pid)
		case other.Str("state") == "queued" && other.Truthy("slot_waiting"):
			return false
		}
		return true
	})
	return pids, alone
}

// queued is runs/.slots.queue as Python's gate.slot_queue reads it: the file, the waits first in
// line of the last runs let in, and when the last went in, none where the file holds no queue;
// false where it holds one in a shape Python's gate never writes, which Go might read otherwise.
func queued() (*run.Object, []any, float64, bool) {
	saved, err := run.ReadJSON(filepath.Join(run.Runs(), ".slots.queue"))
	if saved == nil {
		return nil, nil, 0, !errors.Is(err, run.ErrLoneSurrogate)
	}
	queue, listed := saved.Get("queue").([]any)
	waits, timed := saved.Get("took").([]any)
	turns, kept := saved.Get("turns").([]any)
	_, since := optional(saved.Get("since"))
	lastIn, last := optional(saved.Get("last_in"))
	_, at := saved.Get("at").(run.Number)
	if !at || !whole(saved.Get("running")) || !listed || !since || !last ||
		!timed && saved.Get("took") != nil || !kept && saved.Has("turns") ||
		slices.ContainsFunc(queue, func(id any) bool { _, text := id.(string); return !text }) ||
		slices.ContainsFunc(waits, func(wait any) bool { _, number := wait.(run.Number); return !number }) ||
		slices.ContainsFunc(turns, malformedTurn) {
		return nil, nil, 0, false
	}
	var took []any
	for _, wait := range waits {
		parsed, _ := run.Num(wait)
		took = append(took, run.Float(parsed))
	}
	return saved, took, lastIn, true
}

// optional is a number the queue may leave out, 0 for none.
func optional(value any) (float64, bool) {
	if value == nil {
		return 0, true
	}
	return run.Num(value)
}

// whole is whether the value is a JSON integer, as Python's gate writes a count.
func whole(value any) bool {
	number, ok := value.(run.Number)
	_, err := strconv.Atoi(string(number))
	return ok && err == nil
}

// malformedTurn is whether a seat's turns in the queue are other than Python writes them: a list,
// whose seven-long ones key a seat by five plain values, then count its turns and list its waiters.
func malformedTurn(turn any) bool {
	parts, ok := turn.([]any)
	if !ok {
		return true
	}
	if len(parts) != 7 {
		return false
	}
	_, waiters := parts[6].([]any)
	return !whole(parts[5]) || !waiters || slices.ContainsFunc(parts[:5], func(part any) bool {
		switch part.(type) {
		case nil, bool, string, run.Number:
			return false
		}
		return true
	})
}

// claim writes the queue as Python's claim_slot leaves it on letting the run in, nobody waiting and
// the run's own wait first in line none, then the run's receipt holding its slot, and lets the
// slots lock go.
func (a *admission) claim(dir string, record *run.Object) error {
	defer a.release()
	at := record.Get("slot_started_at")
	took := append(a.took, run.Float(0))
	saved := run.Fields("at", at, "running", a.running+1, "queue", []any{}, "since", at,
		"took", took[max(0, len(took)-20):], "last_in", at, "turns", []any{})
	temp := filepath.Join(run.Runs(), ".slots.queue.tmp")
	if err := os.WriteFile(temp, []byte(run.Line(saved)), 0o666); err != nil {
		return err
	}
	if err := os.Rename(temp, filepath.Join(run.Runs(), ".slots.queue")); err != nil {
		return err
	}
	record.Delete("reservation_pending")
	return run.Create(dir, record)
}

// release lets the slots lock go, where the admission still holds it.
func (a *admission) release() {
	if a != nil && a.slots != nil {
		a.slots.Close()
		a.slots = nil
	}
}
