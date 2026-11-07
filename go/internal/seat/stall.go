package seat

import (
	"fmt"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// stallWait is how long a stall line stands before anything is typed past it (watch.STALL_WAIT).
const stallWait = 180

// plainStall are the fields of a stall waiting on no window, which watch.observe and its signature
// write, its last nudge and its question to the owner.
var plainStall = []string{"since", "pane", "changed_at", "stall_line", "stall_at", "signature", "nudged_at", "told"}

// PlainStalls is whether each of watch.json's `stalls` is a stall of the seat's screen that waits
// on no window and is no other episode (`kind`).  All a seat's word reads of one is that it is
// held (watch.goes_back) and whether its owner was asked (stallTold).
func PlainStalls(stalls *run.Object) bool {
	return !slices.ContainsFunc(stalls.Keys(), func(name string) bool {
		entry, ok := stalls.Get(name).(*run.Object)
		return !ok || slices.ContainsFunc(entry.Keys(), func(key string) bool { return !slices.Contains(plainStall, key) })
	})
}

// KeepStall is the health row's look at the stall the seat's screen shows (watch.health): its
// entry, the one held or a new one, observed on this capture as watch.observe ages the error line
// and the screen apart, the line saying nothing is typed yet; false where its plan may be done
// unprompted, which Go leaves to Python.  Once it has stood quiet for stallWait, pastWait decides.
func KeepStall(live Live, held *run.Object, now float64) (*run.Object, string, bool) {
	if mayRestDone(live.Name) {
		return nil, "", false
	}
	entry := run.NewObject()
	if held != nil {
		entry = held.Copy()
	} else {
		entry.Set("since", run.Float(now))
	}
	if !run.Equal(entry.Get("pane"), live.Pane) {
		run.SetAll(entry, "pane", live.Pane, "changed_at", run.Float(now), "since", run.Float(now))
	}
	marks, _ := config.Words(live.Own, "stall", "signatures")
	lines, line := config.SplitLines(live.Pane), ""
	for at := len(lines) - 1; at >= 0 && line == ""; at-- {
		if slices.ContainsFunc(marks, func(mark string) bool { return harness.Says(lines[at], mark) }) {
			line = lines[at]
		}
	}
	if !run.Equal(entry.Get("stall_line"), line) {
		run.SetAll(entry, "stall_line", line, "stall_at", run.Float(now), "since", run.Float(now))
	}
	entry.Set("signature", live.Stall)
	quiet := now - max(at(entry.Get("stall_at")), at(entry.Get("changed_at")))
	if quiet >= stallWait {
		return pastWait(live, entry, now)
	}
	return entry, fmt.Sprintf("%s: %v for %s; nothing is typed until it has stood for %d minutes", live.Name, live.Stall, span(quiet), stallWait/60), true
}

// stallHeld is whether the climb's watch.json holds a stall of the seat's.
func (facts climbing) stallHeld() bool {
	return facts.tick != nil && facts.tick.Dict("stalls") != nil && facts.tick.Dict("stalls").Truthy(facts.name)
}
