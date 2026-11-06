package tick

import (
	"fmt"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/launch"
	"agentkit/internal/run"
	"agentkit/internal/update"
)

// A stall is work that waits while nothing moves it, judged against its own pace, as Python's
// agentkit/stuck.py finds it: the audit seat is told one stall at a time, each once (`told`), and
// state/stuck.json keeps the line being told and how far its delivery got.
const (
	stallSlower  = 3       // a pass or wait this many times its usual is stuck,
	stallFloor   = 30 * 60 // and none shorter than half an hour, however quick its usual
	stallSamples = 3       // fewer finished passes or waits give no pace to compare with
	stallAsked   = "Find why and build the smallest change to ak that keeps it from happening again, " +
		"through the line."
)

// A stall is one of stuck.stalls running now: its key while it runs, what it is about, and its
// line, "" while it is not stuck.
type stall struct{ key, what, line string }

// stuck is Python's stuck.scan: the stall's line still to be told, else a new stall's, written to
// file and logged; nil while nothing new is stuck.  A stall stays one until it ends: its key is
// kept in `told` while it runs, and no longer.
func (t *ticking) stuck(file string) (*run.Object, error) {
	state, _ := run.ReadJSON(file)
	if state == nil {
		state = run.NewObject()
	}
	if state.Truthy("line") && !state.Truthy("delivered") {
		return state, nil
	}
	found, err := stalls(epoch(t.clock()))
	if err != nil {
		return nil, err
	}
	told := []any{}
	for _, key := range state.List("told") {
		if slices.ContainsFunc(found, func(each stall) bool { return key == each.key }) {
			told = append(told, key)
		}
	}
	for _, each := range found {
		if each.line == "" || slices.Contains(told, any(each.key)) {
			continue
		}
		state = run.Fields("about", each.what, "line", each.line, "typed", nil, "delivered", nil,
			"told", append(told, each.key))
		if err := keepLine(file, state); err != nil {
			return nil, err
		}
		t.log.line("stuck: " + each.line)
		return state, nil
	}
	return nil, nil
}

// stalls is Python's stuck.stalls at now, of the run first in line for a slot; errLeft, before
// anything is written, at a stall Go does not read: a landing line's check pass under way while
// its lander lives, whose line its members name, and ~/agentkit owing a commit going live
// (update.owed_live), read wherever this is its checkout.
func stalls(now float64) ([]stall, error) {
	kept, _ := filepath.Glob(filepath.Join(run.Runs(), ".merge-*.passes"))
	for _, path := range kept {
		passes, _ := run.ReadJSON(path)
		if passes != nil && passes.Truthy("started") && len(passes.List("took")) >= stallSamples &&
			run.ProcessActive(passes) {
			return nil, errLeft
		}
	}
	if update.LiveHere(config.Repo()) {
		return nil, errLeft
	}
	first, read := launch.FirstInLine(now)
	if !read {
		return nil, errLeft
	}
	if first == nil {
		return nil, nil
	}
	found := stall{key: "slot:" + first.Run + ":" + string(run.Float(first.Since)), what: "the stall of the slot queue"}
	if past := farPast(first.Took); now-first.Since > past {
		found.line = fmt.Sprintf("ak stalled: %s has been first in line for a slot for %s, more than %s, "+
			"with %d behind it; `ak run status` shows what it waits on. %s",
			first.Run, run.Span(now-first.Since), run.Span(past), first.Behind, stallAsked)
	}
	return []stall{found}, nil
}

// farPast is how long a pass or wait runs before it is stuck: stallSlower times the median of the
// last (`took`), and stallFloor at least; stallFloor while fewer than stallSamples give it a pace.
func farPast(took []float64) float64 {
	if len(took) < stallSamples {
		return stallFloor
	}
	sorted := slices.Sorted(slices.Values(took))
	middle := len(sorted) / 2
	median := sorted[middle]
	if len(sorted)%2 == 0 {
		median = (sorted[middle-1] + sorted[middle]) / 2
	}
	return max(stallFloor, stallSlower*median)
}
