package host

import (
	"io/fs"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// SeatScope is every process in the seat's own scope that holds pid, below it too, as Python's
// host.cgroup_pids(complete=True) reads them: false where pid is in no seat's scope
// (`agentkit-seat-…`), nil where a list cannot be read, which may hide any process.
func SeatScope(pid int) ([]int, bool) {
	relative, ok := processCgroup(pid)
	if !ok || !strings.HasPrefix(filepath.Base(relative), "agentkit-seat-") {
		return nil, false
	}
	pids, _ := cgroupPids(relative)
	return pids, true
}

// cgroupPids is every process in the cgroup at relative, below it too, Python's
// host.cgroup_pids(complete=True): nil and false where a list cannot be read, which may hide any
// process.
func cgroupPids(relative string) ([]int, bool) {
	pids, complete := []int{}, true
	filepath.WalkDir(cgroupPath(relative), func(dir string, entry fs.DirEntry, err error) error {
		if err != nil {
			complete = false
			return nil
		}
		if !entry.IsDir() {
			return nil
		}
		// a group's own list leaves out its children's; a threaded child's never reads, its
		// processes being on its thread root's
		data, err := os.ReadFile(filepath.Join(dir, "cgroup.procs"))
		if err != nil {
			complete = false
			return nil
		}
		for _, word := range strings.Fields(string(data)) {
			held, err := strconv.Atoi(word)
			if err != nil {
				complete = false
				return nil
			}
			pids = append(pids, held)
		}
		return nil
	})
	if !complete {
		return nil, false
	}
	return pids, true
}
