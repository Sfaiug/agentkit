// Package turn is this host's heavy-suite turns, Python's gate.gate_turn.  A host runs only as many
// heavy suites at once as its readings fit, or as `max_gates` pins, each holding a turn while it
// runs: a lock on one of the turn files Python's suites lock too, so a host running both never runs
// more, and which the kernel lets go with its holder.  A freed turn goes to the waiter that ranks
// first: a line's own check, then a run's own landing check, then a round's, each the one that has
// waited longest first, then by run.  Each is seen waiting as Python sees one: a landing check by a
// file of its own beside the runs, a line's check also by its share of the lock host keeps for them,
// a round's by the mark on its record.
package turn

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync/atomic"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// Poll is how often a waiter looks for a turn again, and how long a busy suite gives its turn back
// for, Python's GATE_POLL.
var Poll = 15 * time.Second

// An Ask is a check's wait for turns for the run at Dir, or, Line, a line's own check of that member,
// which marks no record.  A suite in Pieces, each costing CPUs and MemoryMB, takes every turn they
// fit; any other check takes one.  The wait is said to Say and in the check's Log, and Poll is asked
// each poll: true ends the wait holding no turn, an error ends it with that error.
type Ask struct {
	Dir            string
	Line           bool
	Pieces         bool
	CPUs, MemoryMB float64
	Log            string
	Say            func(string)
	Poll           func() (bool, error)
}

// A Hold is the turns a check holds; a nil one holds none.
type Hold struct {
	ask      Ask
	id, repo string
	landing  bool    // a line's or a run's own landing check
	since    float64 // where it ranks among waiters of its kind
	places   int     // the limit it was admitted at: the most turns its pieces run on
	turns    []held
	said     bool // a config it cannot read, said once
	waited   bool // a piece waited for a turn (Waited)
}

// A held turn is a turn file's index and its locked file.
type held struct {
	index int
	file  *os.File
}

// Take waits for this host's turns, Python's _acquire_gate_turn: nil, holding none, for a run with no
// repository, under the test suites' AK_MAX_RUNS=0, where `max_gates = 0` leaves an ordinary check
// uncapped, and where Poll ends the wait.  A free turn is taken only when no waiter ranks before it,
// and the limit is read again at each look, so a changed pin or headroom reaches those waiting.
func Take(ctx context.Context, ask Ask) (*Hold, error) {
	record, _ := run.Read(ask.Dir)
	if record == nil || record.Str("repo") == "" || os.Getenv("AK_MAX_RUNS") == "0" {
		return nil, nil
	}
	h := &Hold{ask: ask, id: filepath.Base(ask.Dir), repo: record.Str("repo"), landing: ask.Line || record.Truthy("landing"), since: now()}
	if !ask.Pieces {
		h.ask.CPUs, h.ask.MemoryMB = host.Cost(0, 0)
	}
	switch wait := record.Dict("waiting_on"); {
	case ask.Line && wait != nil:
		if joined, ok := wait.Num("joined"); ok {
			h.since = joined
		}
	case h.landing && !ask.Line:
		// a run's landing ranks from its first landing wait, as a waiter on older code reads it
		if first, ok := host.FirstLandingWait(ask.Dir); ok {
			h.since = first
		} else {
			host.SeedLandingWait(ask.Dir, h.since)
		}
	}
	unseen := h.seen()
	got, limit, running := h.admit()
	waits := limit > 0 && (len(got) == 0 || h.before())
	var kept []byte
	var err error
	if waits {
		kept, _ = os.ReadFile(ask.Log)
		got, limit, err = h.wait(ctx, got, limit, running)
	}
	unseen() // seen waiting until it holds turns or gives up, before its log says anything else
	if waits {
		os.WriteFile(ask.Log, kept, 0o666) // the wait's line gives way to what the log held
	}
	if len(got) == 0 {
		return nil, err
	}
	h.places, h.turns = limit, got
	return h, nil
}

// wait gives back what admit took and looks again each poll until it holds turns no waiter ranks
// before, saying so on the run's record; none where Poll or ctx ends it, or a pin leaves no cap.
// The log says the wait each poll, so a run's silence reads it as life.
func (h *Hold) wait(ctx context.Context, got []held, limit, running int) ([]held, int, error) {
	said := func() string {
		return fmt.Sprintf("waiting for a heavy suite turn · %d running · %d more fit", running, max(0, limit-running))
	}
	h.ask.Say("done-when: " + said())
	defer h.marked()()
	began := time.Now()
	for {
		release(got)
		os.WriteFile(h.ask.Log, []byte(said()+"\n"), 0o666)
		select {
		case <-ctx.Done():
			return nil, 0, context.Cause(ctx)
		case <-time.After(Poll):
		}
		if h.ask.Poll != nil {
			if done, err := h.ask.Poll(); done || err != nil {
				return nil, 0, err
			}
		}
		if got, limit, running = h.admit(); limit == 0 {
			return nil, 0, nil
		}
		if len(got) > 0 && !h.before() {
			break
		}
	}
	h.ask.Say("done-when: took a heavy suite turn after " + run.Span(time.Since(began).Seconds()))
	return got, limit, nil
}

// Places is the most turns the hold's pieces run on: the limit it was admitted at.
func (h *Hold) Places() int { return h.places }

// Grow calls start once for each turn the hold has, a place for its pieces, and, until over says
// none waits or runs, joins the turns this host frees to it each time waiting says a piece waits for
// one, as one a machine lost waits again, up to Places, and calls start for each, Python's
// _GateHold.take: the suite waits as one waiter, at the place it was admitted at.
func (h *Hold) Grow(ctx context.Context, waiting, over func() bool, start func()) {
	for range h.turns {
		start()
	}
	for len(h.turns) < h.places && !over() && ctx.Err() == nil {
		if waiting() {
			h.join(ctx, waiting, start)
		}
		select {
		case <-ctx.Done():
		case <-time.After(time.Second):
		}
	}
}

// join joins the turns this host frees to the hold while waiting says a piece waits, seen waiting
// meanwhile.
func (h *Hold) join(ctx context.Context, waiting func() bool, start func()) {
	h.waited = true
	defer h.seen()()
	defer h.marked()()
	var asked time.Time
	for len(h.turns) < h.places && waiting() && ctx.Err() == nil {
		if time.Since(asked) >= Poll {
			asked = time.Now()
			got, _, _ := h.admit()
			if len(got) > 0 && h.before() {
				release(got)
				got = nil
			}
			for _, turn := range got {
				if len(h.turns) == h.places {
					release([]held{turn})
					continue
				}
				h.turns = append(h.turns, turn)
				start()
			}
		}
		// a piece taking the last waiting one ends the wait within a second, not a poll
		select {
		case <-ctx.Done():
		case <-time.After(time.Second):
		}
	}
}

// Alone gives back every turn but one, for what runs alone once the pieces ended.
func (h *Hold) Alone() {
	if h != nil && len(h.turns) > 1 {
		release(h.turns[1:])
		h.turns = h.turns[:1]
	}
}

// Give gives back every turn the hold has.
func (h *Hold) Give() {
	if h != nil {
		release(h.turns)
		h.turns = nil
	}
}

func release(turns []held) {
	for _, turn := range turns {
		turn.file.Close()
	}
}

// admit locks the turns free now that the hold may take, Python's admit: one, or for pieces as many
// as fit beside those running, its own turns counted among them, in turn order; the limit, pinned
// or derived from the readings, and how many run.  A pin holds no suite in pieces.
func (h *Hold) admit() (got []held, limit, running int) {
	limit = -1
	if !h.ask.Pieces {
		var err error
		if limit, err = config.MaxGates(); err != nil {
			if !h.said {
				h.said = true
				h.ask.Say(fmt.Sprintf("done-when: %v · the heavy suite takes a derived turn", err))
			}
			limit = -1
		}
	}
	var readings host.Readings
	if limit < 0 {
		readings = host.Read() // read before any lock: sampling the CPU waits, which would count those as running
	}
	mine := map[int]bool{}
	for _, turn := range h.turns {
		mine[turn.index] = true
	}
	running = len(h.turns)
	free := map[int]*os.File{}
	looked := host.HeavyTurns(1)
	for index, path := range looked {
		if mine[index] {
			continue
		}
		file, err := lock.Try(path)
		switch {
		case errors.Is(err, lock.ErrHeld):
			running++
		case err == nil:
			free[index] = file
		}
	}
	if limit < 0 {
		limit = readings.Fit(running, h.ask.CPUs, h.ask.MemoryMB, h.ask.Pieces)
	}
	wanted := 1
	if h.ask.Pieces {
		wanted = limit - running
	}
	paths := host.HeavyTurns(limit)
	for index := 0; index < limit && running < limit && len(got) < wanted; index++ {
		file, ok := free[index]
		if index >= len(looked) {
			// a turn file the first look did not find
			var err error
			file, err = lock.Try(paths[index])
			ok = err == nil
		}
		if ok {
			delete(free, index)
			got = append(got, held{index, file})
		}
	}
	for _, file := range free {
		file.Close()
	}
	return got, limit, running
}

// A rank orders waiters, the least first, Python's tuple: a landing check before a round's, a line's
// own before a run's, the longest waiting, then by run.
type rank struct {
	notLanding, notLine bool
	since               float64
	id                  string
}

func (a rank) before(b rank) bool {
	switch {
	case a.notLanding != b.notLanding:
		return !a.notLanding
	case a.notLine != b.notLine:
		return !a.notLine
	case a.since != b.since:
		return a.since < b.since
	}
	return a.id < b.id
}

// before is whether a live waiter ranks before the hold, Python's _gate_waiter_before: a round check
// stays behind any line's check waiting, and a landing wait's own file ranks it, a record's mark only
// a landing run with none.  A mark whose process is gone, or whose pid is not its record's, holds
// nobody back.
func (h *Hold) before() bool {
	if !h.landing && host.LineCheckWaits() {
		return true
	}
	me := rank{!h.landing, !h.ask.Line, h.since, h.id}
	filed := map[string]bool{}
	for _, wait := range landingWaits() {
		if wait.id != h.id && wait.before(me) {
			return true
		}
		filed[wait.id] = true
	}
	for _, dir := range run.Dirs() {
		id := filepath.Base(dir)
		record, _ := run.Read(dir)
		if id == h.id || record == nil || record.Str("state") != "running" {
			continue
		}
		turn := record.Dict("gate_turn")
		if turn == nil || !run.Equal(turn.Get("pid"), record.Get("pid")) || !run.ProcessActive(record) {
			continue
		}
		landing := turn.Truthy("landing")
		if landing && filed[id] {
			continue
		}
		waited, ok := turn.Num("since")
		if first, found := host.FirstLandingWait(dir); landing && found {
			waited, ok = first, true
		}
		if !ok {
			waited = 0
		}
		if (rank{!landing, true, waited, id}).before(me) {
			return true
		}
	}
	return false
}

// seen is the hold seen waiting by those ranking against it, Python's landing_wait, until what it
// answers is called: a landing check by a file of its own saying when its wait began and for which
// run, locked before it takes its name, so a file under that name is never an unheld live one, and a
// line's check also by host.LineCheckWaiting.  A round check's mark is its record's.
func (h *Hold) seen() func() {
	if !h.landing {
		return func() {}
	}
	runs := run.Runs()
	var shared *os.File
	if h.ask.Line {
		shared = host.LineCheckWaiting()
	}
	token := fmt.Sprintf("%d-%d-%d", os.Getpid(), tokens.Add(1), time.Now().UnixNano())
	draft, path := filepath.Join(runs, ".landing-draft-"+token), filepath.Join(runs, ".landing-wait-"+token)
	file, err := lock.Try(draft)
	if err == nil {
		_, err = file.WriteString(run.Line(run.Fields("since", h.since, "run_id", h.id, "line", h.ask.Line)))
	}
	if err == nil {
		err = os.Rename(draft, path)
	}
	if err != nil {
		// Windows names no file open, and no Python reads it there: its waiters rank by records
		if file != nil {
			file.Close()
			file = nil
		}
		os.Remove(draft)
	}
	return func() {
		if err == nil {
			os.Remove(path)
		}
		if file != nil {
			file.Close()
		}
		if shared != nil {
			shared.Close()
		}
	}
}

var tokens atomic.Int64

// marked puts the wait on the run's record, Python's mark_gate_wait, `waiting for a heavy suite
// turn` as listings say it, until what it answers is called: the process waiting, the repository,
// and where it ranks; a line's check marks no record.
func (h *Hold) marked() func() {
	if h.ask.Line {
		return func() {}
	}
	mark := func(on bool) {
		run.Change(h.ask.Dir, func(record *run.Object) error {
			if record.Str("state") != "running" {
				return nil
			}
			if !on {
				record.Delete("gate_turn")
				return nil
			}
			turn := run.Fields("pid", os.Getpid(), "of", h.repo, "since", h.since)
			if h.landing {
				turn.Set("landing", true)
			}
			record.Set("gate_turn", turn)
			return nil
		})
	}
	mark(true)
	return func() { mark(false) }
}

// A landing wait's file, as Python's _landing_waiters reads it.
func landingWaits() (found []rank) {
	for _, path := range config.Glob(run.Runs(), ".landing-wait-*") {
		if !lock.Held(path) {
			os.Remove(path) // its waiter is gone
			continue
		}
		data, _ := os.ReadFile(path)
		decoded, _ := run.Decode(data)
		wait, _ := decoded.(*run.Object)
		if wait == nil {
			continue
		}
		since, ok := wait.Num("since")
		if ok {
			found = append(found, rank{false, !wait.Truthy("line"), since, run.Text(wait.Get("run_id"))})
		}
	}
	return found
}

func now() float64 { return float64(time.Now().UnixNano()) / 1e9 }
