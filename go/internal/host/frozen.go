package host

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// Frozen reads the process's cgroup and its ancestors without asking the held process.
func Frozen(pid int) bool {
	data, _ := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/cgroup")
	for _, line := range strings.Split(string(data), "\n") {
		if relative, unified := strings.CutPrefix(line, "0::"); unified {
			return frozenCgroup(relative)
		}
	}
	return false
}

func frozenCgroup(relative string) bool {
	root := cgroupPath("")
	for group := cgroupPath(relative); group == root || strings.HasPrefix(group, root+string(filepath.Separator)); group = filepath.Dir(group) {
		data, _ := os.ReadFile(filepath.Join(group, "cgroup.freeze"))
		if strings.TrimSpace(string(data)) == "1" {
			return true
		}
		if group == root {
			break
		}
	}
	return false
}
