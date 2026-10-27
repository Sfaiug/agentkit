package host

import (
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"agentkit/internal/tmux"
)

// SliceLine is the one line the screens say about where the agents run. `no slice` is no
// warning: a host with no user systemd manager starts its seats plainly.
func SliceLine() string {
	if !userManager() {
		return "no slice (no user systemd manager)"
	}
	return sliceLine(sliceCgroup(), sliceCeiling())
}

// sliceLine reads the slice's tasks, and its ceiling, else the drop-ins' `ceiling`. A slice
// with nothing in it has no directory, so holds no tasks.
func sliceLine(cgroup string, ceiling float64) string {
	tasks, counted := number(filepath.Join(cgroup, "pids.current"))
	limit, limited := number(filepath.Join(cgroup, "pids.max"))
	if limited {
		ceiling = limit
	}
	counted = counted || !limited
	room := "no ceiling set"
	if counted && ceiling > 0 {
		room = fmt.Sprintf("%v%% of its ceiling", math.RoundToEven(100*tasks/ceiling))
	}
	plural := "s"
	if tasks == 1 {
		plural = ""
	}
	return fmt.Sprintf("slice %s.slice · %v task%s · %s", tmux.Own(), tasks, plural, room)
}

// sliceCeiling is the task ceiling the drop-ins set, 0 where none does: the live one appears
// with the slice's first process. The last file to name it wins, as systemd reads them.
func sliceCeiling() float64 {
	configHome := os.Getenv("XDG_CONFIG_HOME")
	if configHome == "" {
		home, _ := os.UserHomeDir()
		configHome = filepath.Join(home, ".config")
	}
	found := 0.0
	for _, base := range []string{"systemd/user", "systemd/user.control"} {
		files, _ := filepath.Glob(filepath.Join(configHome, base, tmux.Own()+".slice.d", "*.conf"))
		sort.Strings(files)
		for _, file := range files {
			data, _ := os.ReadFile(file)
			for _, line := range strings.Split(string(data), "\n") {
				key, value, _ := strings.Cut(line, "=")
				if ceiling, err := strconv.ParseUint(strings.TrimSpace(value), 10, 64); err == nil && strings.TrimSpace(key) == "TasksMax" {
					found = float64(ceiling)
				}
			}
		}
	}
	return found
}
