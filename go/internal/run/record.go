// Package run reads and writes run records in Python ak's format, which both programs share
// until the switch, and holds the words a record's state says.
package run

import (
	"os"
	"path/filepath"
	"slices"
	"sort"
	"time"

	"agentkit/internal/config"
)

// The state words a record holds, grouped by what ak asks of them.
var (
	active = []string{"queued", "running"}        // a loop works the run, or is about to
	failed = []string{"fail", "error", "blocked"} // ended with nothing delivered, not by choice
	ended  = slices.Concat([]string{"pass"}, failed, []string{"stopped", "not_needed"})
	goes   = []string{"queued", "running", "waiting", "exhausted", "stalled", "waiting_login"}
)

func stateIn(record *Object, words []string) bool {
	return slices.Contains(words, record.Str("state"))
}

func Active(record *Object) bool { return stateIn(record, active) }
func Failed(record *Object) bool { return stateIn(record, failed) }
func Ended(record *Object) bool  { return stateIn(record, ended) }

const (
	SilenceMinutes = 20 // no command output or harness event for this long is a death
	CeilingHours   = 6  // the whole done-when list, even if it keeps printing
)

// Runs is where every run keeps its directory.
func Runs() string {
	return filepath.Join(config.Home(), "runs")
}

// Dirs are the run directories, in name order.
func Dirs() []string {
	entries, err := os.ReadDir(Runs())
	if err != nil {
		return nil
	}
	var dirs []string
	for _, entry := range entries {
		path := filepath.Join(Runs(), entry.Name())
		if info, err := os.Stat(path); err == nil && info.IsDir() {
			dirs = append(dirs, path)
		}
	}
	sort.Strings(dirs)
	return dirs
}

// ReadJSON is the object a file holds, or nil where it is missing, unreadable or no object;
// the error is ErrLoneSurrogate where Python reads what Go cannot keep.
func ReadJSON(path string) (*Object, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return object(data)
}

// object is the object JSON text holds, as ReadJSON reads one.
func object(data []byte) (*Object, error) {
	value, err := Decode(data)
	record, _ := value.(*Object)
	return record, err
}

// Read is the run's record, as ReadJSON reads its run.json.
func Read(dir string) (*Object, error) {
	return ReadJSON(filepath.Join(dir, "run.json"))
}

// Reap is the record as Python's reap leaves an ended run a listing reads, and whether that
// reap would end what the run started: a passed or failed run whose loop died before its final
// cleanup is swept once per loop, the sweep stamped as `tree_stopped`; a stop and a run found
// not needed ended theirs on purpose.  A run that recorded no pid and no scope started nothing
// to sweep, so only the stamp changes, here in memory alone.
func Reap(record *Object) (*Object, bool) {
	loop := []any{record.Get("pid"), record.Get("process_identity")}
	if !(Failed(record) || record.Str("state") == "pass") || ProcessActive(record) || Equal(record.Get("tree_stopped"), loop) {
		return record, false
	}
	if record.Get("pid") != nil || record.Get("scope") != nil {
		return record, true
	}
	reaped := record.Copy()
	reaped.Set("tree_stopped", loop)
	return reaped, false
}

// LookedAt marks an ending looked at, as opening the run by id does, and is whether it marked:
// once, and never an error whose retry the tick keeps, which only a stop cancels.
func LookedAt(record *Object, now time.Time) bool {
	if !Ended(record) || record.Str("state") == "error" && Going(record, now) || record.Truthy("recovery_acknowledged_at") {
		return false
	}
	record.Set("recovery_acknowledged_at", seconds(now))
	record.Delete("error_retry_at")
	record.Delete("error_retries")
	return true
}
