package seat

import (
	"io/fs"
	"path/filepath"
	"slices"
	"strings"
)

// updateFiles are what `ak update` and the tick's upgrade keep in state/ beside their folders,
// which only agentkit/update.py reads: the swaps under way, the checks' last passes and the
// logins they wait for, what agentkit's move said and still owes, and the releases asked.  The
// update package imports this one, so they are named here.
var updateFiles = []string{"harness-swaps.json", "live-check-passed", "fresh-check-passed", "live-check-held",
	"fresh-check-held", "upgrade-check-held", "agentkit-install-pending", "harness-latest.json", "harness-update-said.json"}

// updateRecord is whether a state/ entry is one of update's records, which say nothing a seat's
// word hangs on: its gates', faults' and live checks' folders, or one of updateFiles, or the
// `.tmp` it is written through (update._put), or the commit agentkit's move said last, by where.
func updateRecord(entry fs.DirEntry) bool {
	name := entry.Name()
	if entry.IsDir() {
		return slices.Contains([]string{"harness-gates", "fresh-gate-faults", "live-checks"}, name)
	}
	return entry.Type().IsRegular() && (strings.HasPrefix(name, "agentkit-said-") || slices.ContainsFunc(updateFiles, func(file string) bool {
		return name == file || name == strings.TrimSuffix(file, filepath.Ext(file))+".tmp"
	}))
}
