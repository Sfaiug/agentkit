//go:build linux

package box

import (
	"errors"
	"fmt"
	"io/fs"
	"maps"
	"os"
	"slices"
	"syscall"
)

// A report is how a box's command ended, as Python's box._supervise writes it.
type report struct {
	Returncode int      `json:"returncode"`
	Processes  [][2]any `json:"processes"`
	CPUSeconds float64  `json:"cpu_seconds"`
}

// reported is the report of a command that ended with that status, leaving those processes: what
// the first process's exit would end ends now and is reaped, so every process's CPU, a server's
// the command left running included, is in its children's, final.
func reported(code int, left map[int]string) report {
	if os.Getpid() == 1 {
		syscall.Kill(-1, syscall.SIGKILL)
		for {
			if _, err := syscall.Wait4(-1, nil, 0, nil); errors.Is(err, syscall.ECHILD) {
				break
			}
		}
	}
	found := report{Returncode: code, Processes: [][2]any{}}
	for _, pid := range slices.Sorted(maps.Keys(left)) {
		found.Processes = append(found.Processes, [2]any{pid, left[pid]})
	}
	var spent syscall.Rusage
	if syscall.Getrusage(syscall.RUSAGE_CHILDREN, &spent) == nil {
		found.CPUSeconds = float64(spent.Utime.Nano()+spent.Stime.Nano()) / 1e9
	}
	return found
}

// commandFailed says why a command never started, keeping the shell's 127 or 126: it proves no
// defect.
func commandFailed(err error) (int, map[int]string) {
	fmt.Fprintln(os.Stderr, err)
	if errors.Is(err, fs.ErrNotExist) {
		return 127, nil
	}
	return 126, nil
}
