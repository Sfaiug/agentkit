package seat

import (
	"fmt"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/screen"
)

const (
	nudgeEvery = 180  // at most one keystroke per seat in that many seconds (watch.NUDGE_EVERY)
	giveUp     = 3600 // an hour of it: the owner is asked, once, and the nudging stops (watch.GIVE_UP)
)

// pastWait is the health row's look at a stall that has stood quiet for stallWait (watch.health).
// One its window may be refusing waits out that window, and one whose nudge is due is typed past:
// both are Python's.  One nudged within nudgeEvery is kept as it is.  One an hour old is the
// owner's: the stall in plain words becomes the seat's question, and watch.json marks the stall
// told, where the seat's word reads it.  Nothing is typed, then or after.
func pastWait(live Live, entry *run.Object, now float64) (*run.Object, string, bool) {
	if windowRefused(live) {
		return nil, "", false
	}
	stood := now - at(entry.Get("since"))
	if stood < giveUp {
		return entry, "", now-at(entry.Get("nudged_at")) < nudgeEvery
	}
	text := fmt.Sprintf("%s is stalled on %v for an hour and typing has not moved it; open the host, "+
		"press this session's number, and get it going again.", live.Name, live.Stall)
	line := fmt.Sprintf("%s: stalled on %v for %s; asked the user", live.Name, live.Stall, span(stood))
	if drying != nil {
		return entry, "would notify needs: " + text + "\n" + line, true
	}
	// Health holds watch.lock where watch.json held this stall untold (stallUntold), as it still
	// does unless a forget has taken it away or another ask told it since: either is Python's.
	asking := false
	err := rewrite(filepath.Join(config.Home(), "state", "watch.json"), run.Encode, false, func(data *run.Object) bool {
		held := stallOf(data, live.Name)
		if asking = held != nil && !held.Truthy("told"); !asking {
			return false
		}
		if err := notify.Alert(live.Name, text, "stall:"+live.Name+":"+run.Text(entry.Get("since")), Stderr); err != nil {
			line = "WARN " + live.Name + ": notification was not accepted; retry required"
			return false
		}
		entry.Set("told", run.Float(now))
		data.Dict("stalls").Set(live.Name, entry)
		return true
	})
	if err != nil || !asking {
		return nil, "", false
	}
	return entry, line, true
}

// windowRefused is whether the stall may be the seat's window refusing its turns, which
// watch.health waits out (watch.failed_on's SPENT or LIMITED): its record ending on such a refusal
// (Refused), or the last two lines its harness drew saying one, which hold every line
// watch.error_said reads.
func windowRefused(live Live) bool {
	lines := eyeOf(live.Own).rules.Said(screen.Tail(live.Pane))
	refused, _ := harness.Refusal(live.Own, strings.Join(lines[max(0, len(lines)-2):], "\n"))
	return live.Refused != "" || refused
}

// stallOf is the stall watch.json's data holds of that seat, nil for none.
func stallOf(data *run.Object, name string) *run.Object {
	if data == nil || data.Dict("stalls") == nil {
		return nil
	}
	entry, _ := data.Dict("stalls").Get(name).(*run.Object)
	return entry
}

// stallUntold is whether the watch.json in state holds a stall of that seat whose owner nobody has
// asked about yet, which pastWait may ask about.
func stallUntold(state, name string) bool {
	data, _ := run.ReadJSON(filepath.Join(state, "watch.json"))
	held := stallOf(data, name)
	return held != nil && !held.Truthy("told")
}

// stallTold is whether the watch.json in state holds a stall of that seat its owner was asked
// about, which the tick no longer types past.
func stallTold(state, name string) bool {
	data, _ := run.ReadJSON(filepath.Join(state, "watch.json"))
	held := stallOf(data, name)
	return held != nil && held.Truthy("told")
}
