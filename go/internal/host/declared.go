package host

import (
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

// Declared says, for a Watch, whether a command among the marker's processes is inside the time
// it gave `timeout`, Python's worker.within_declared_timeout: a command started under `timeout`
// has said how long it may take, however little it prints, so its silence is no hang before that
// bound.
func Declared(marker string) func(now float64) bool {
	return func(now float64) bool { return DeclaredIn("/proc", Marked(marker), now) }
}

// DeclaredIn is whether any of those pids, read in the /proc at proc, is a `timeout N` still
// inside its N seconds, Python's worker.declared_in.
func DeclaredIn(proc string, pids []int, now float64) bool {
	boot := booted()
	for _, pid := range pids {
		said, err := os.ReadFile(proc + "/" + strconv.Itoa(pid) + "/cmdline")
		if err != nil {
			continue
		}
		seconds := TimeoutSeconds(strings.Split(string(said), "\x00"))
		if stat, ok := ReadStatIn(proc, pid); ok && !stat.Exited() && seconds > 0 &&
			now-boot-float64(stat.Start)/clockTicks < seconds {
			return true
		}
	}
	return false
}

var timeoutSpan = regexp.MustCompile(`^(\d+\.?\d*|\.\d+)([smhd]?)$`)

// TimeoutSeconds is the duration `timeout(1)` was given in that argv, 0 for any other command or
// none, Python's worker.timeout_seconds.
func TimeoutSeconds(argv []string) float64 {
	if len(argv) == 0 || filepath.Base(argv[0]) != "timeout" {
		return 0
	}
	for i := 1; i < len(argv); i++ {
		word := argv[i]
		switch {
		case word == "-k" || word == "-s" || word == "--kill-after" || word == "--signal":
			i++
		case word == "--" || !strings.HasPrefix(word, "-"):
			if word == "--" {
				if i++; i == len(argv) {
					return 0
				}
				word = argv[i]
			}
			found := timeoutSpan.FindStringSubmatch(word)
			if found == nil {
				return 0
			}
			value, _ := strconv.ParseFloat(found[1], 64)
			return value * map[string]float64{"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[found[2]]
		}
	}
	return 0
}
