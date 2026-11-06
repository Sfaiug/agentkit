//go:build linux

package box

import (
	"encoding/json"
	"io"
	"os"
	"strconv"
	"sync/atomic"

	"agentkit/internal/host"
)

// infoFD is the descriptor bubblewrap writes what it built to, the box's first process among it.
const infoFD = 5

// A look is how ak sees into a box as its command runs, Python's box.command's began and
// declared: the box is up once its first process made its report, and the box's own /proc,
// reached through that process, holds the command's processes and nothing else, so a look takes
// as long as the command is large, never as long as the host is busy.
type look struct {
	report string
	first  atomic.Int64 // the first process's pid as this host numbers it
}

// read keeps the first process's pid from bubblewrap's information.
func (l *look) read(info io.Reader) {
	var built struct {
		Child int64 `json:"child-pid"`
	}
	if json.NewDecoder(info).Decode(&built) == nil {
		l.first.Store(built.Child)
	}
}

// up is whether the box's first process has started, the command's silence with it.
func (l *look) up() bool {
	_, err := os.Stat(l.report)
	return err == nil
}

// declared is whether a command in the box is inside the time it gave `timeout`: asked once the
// box is up, as until then its first process's root, and the /proc there, are still the host's.
func (l *look) declared(now float64) bool {
	if !l.up() {
		return false
	}
	proc := "/proc/" + strconv.FormatInt(l.first.Load(), 10) + "/root/proc"
	entries, err := os.ReadDir(proc)
	if err != nil {
		return false
	}
	var pids []int
	for _, entry := range entries {
		if pid, err := strconv.Atoi(entry.Name()); err == nil {
			pids = append(pids, pid)
		}
	}
	return host.DeclaredIn(proc, pids, now)
}
