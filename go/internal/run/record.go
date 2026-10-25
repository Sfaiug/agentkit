// Package run reads run records in Python ak's format, which both programs share until the
// switch, and holds the words a record's state says.  It writes none.
package run

import (
	"os"
	"path/filepath"
	"sort"

	"agentkit/internal/config"
)

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
	value, err := Decode(data)
	record, _ := value.(*Object)
	return record, err
}

// Read is the run's record, as ReadJSON reads its run.json.
func Read(dir string) (*Object, error) {
	return ReadJSON(filepath.Join(dir, "run.json"))
}

// What an ended run's loop is swept for once it is gone: a stop and a run found not needed
// ended theirs on purpose.
var swept = []string{"pass", "fail", "error", "blocked"}

// Reap is the record as Python's reap leaves an ended run a listing reads, and whether that
// reap would end what the run started: an ended run whose loop died before its final cleanup
// is swept once per loop, the sweep stamped as `tree_stopped`.  A run that recorded no pid and
// no scope started nothing to sweep, so only the stamp changes, here in memory alone.
func Reap(record *Object) (*Object, bool) {
	loop := []any{record.Get("pid"), record.Get("process_identity")}
	if !stateIn(record, swept) || ProcessActive(record) || equal(record.Get("tree_stopped"), loop) {
		return record, false
	}
	if record.Get("pid") != nil || record.Get("scope") != nil {
		return record, true
	}
	reaped := record.Copy()
	reaped.Set("tree_stopped", loop)
	return reaped, false
}
