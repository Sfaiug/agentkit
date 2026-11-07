package host

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
)

// Measured is the cgroup a change in whose memory is this process's doing, Python's
// _SuiteMeasure's group: its own where that is one of units, its run's systemd scope, else its own
// where that holds nothing but this process and what it started (Python's host.own_cgroup); false
// for neither.
func Measured(units []string) (string, bool) {
	relative, ok := ownCgroup()
	if !ok {
		return "", false
	}
	if slices.Contains(units, filepath.Base(relative)) {
		return cgroupPath(relative), true
	}
	pids, complete := cgroupPids(relative)
	if !complete || !slices.Contains(pids, os.Getpid()) {
		return "", false
	}
	for _, pid := range pids {
		seen := map[int]bool{}
		for pid != os.Getpid() {
			stat, ok := ReadStat(pid)
			if !ok || seen[pid] {
				return "", false
			}
			seen[pid] = true
			pid = stat.Parent
		}
	}
	return cgroupPath(relative), true
}

// ScopeUnits is the unit names a record's scope might be, scope first (turns._scope_units).
func ScopeUnits(scope string) []string {
	switch {
	case scope == "":
		return nil
	case strings.HasSuffix(scope, ".scope") || strings.HasSuffix(scope, ".service"):
		return []string{scope}
	}
	return []string{scope + ".scope", scope + ".service"}
}

// HeldMB is what the cgroup holds in MB, swap included, less the file cache reclaim frees, Python's
// host.held_mb(swap=True): false where unread.
func HeldMB(cgroup string) (float64, bool) {
	held, ok := heldMB(cgroup)
	return held + swapMB(cgroup), ok
}
