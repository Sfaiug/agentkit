package host

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// OOMKills is how many of this process's cgroup's processes the kernel killed for memory, the
// `oom_kill` of its memory.events, Python's _SuiteMeasure.oom("oom_kill"): 0 where none is read.
func OOMKills() int {
	relative, ok := ownCgroup()
	if !ok {
		return 0
	}
	data, _ := os.ReadFile(filepath.Join(cgroupPath(relative), "memory.events"))
	for _, line := range strings.Split(string(data), "\n") {
		if value, found := strings.CutPrefix(line, "oom_kill "); found {
			kills, _ := strconv.Atoi(strings.TrimSpace(value))
			return kills
		}
	}
	return 0
}
