package host

import (
	"os"
	"slices"
	"strconv"
	"strings"
)

// A Child is a process another started directly, by what /proc says of it: its start tells it
// from a later process given the same pid.
type Child struct {
	Pid   int
	Args  []string
	Start int64
}

// Children are that process's direct children, lowest pid first, Python's watch.loop_children:
// none where /proc cannot be read.
func Children(pid int) []Child {
	entries, _ := os.ReadDir("/proc")
	var found []Child
	for _, entry := range entries {
		child, err := strconv.Atoi(entry.Name())
		stat, ok := ReadStat(child)
		if err != nil || !ok || stat.Parent != pid || pid <= 0 {
			continue
		}
		said, _ := os.ReadFile("/proc/" + entry.Name() + "/cmdline")
		args := strings.Split(strings.ToValidUTF8(string(said), "�"), "\x00")
		found = append(found, Child{child, slices.DeleteFunc(args, func(arg string) bool { return arg == "" }), stat.Start})
	}
	slices.SortFunc(found, func(a, b Child) int { return a.Pid - b.Pid })
	return found
}
