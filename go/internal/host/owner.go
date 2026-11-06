package host

import (
	"fmt"
	"os"
	"strings"
)

// Mark marks this process, and so everything it starts, as name's, Python's owner.mark: AK_OWNER
// is `<pid namespace> <pid> <start> <session> <name>`, the namespace by its inode, so what an
// `ak` leaves running is told apart once it is gone, and what ak starts to outlive it goes
// without.  A seat's tag on a side session (AK_TMUX_OWNER) goes first, from what it starts and
// from what /proc shows of it (untag): an `ak` typed in a side session is no more the seat's
// than what it starts.  Where /proc cannot say, the mark inherited, if any, stays.
func Mark(name string) {
	if os.Getenv("AK_TMUX_OWNER") != "" {
		untag()
	}
	os.Unsetenv("AK_TMUX_OWNER")
	link, _ := os.Readlink("/proc/self/ns/pid") // `pid:[<inode>]`
	inode, named := strings.CutPrefix(strings.TrimSuffix(link, "]"), "pid:[")
	if stat, ok := ReadStat(os.Getpid()); ok && named {
		os.Setenv("AK_OWNER", fmt.Sprintf("%s %d %d %d %s", inode, os.Getpid(), stat.Start, stat.Session, name))
	}
}

// Unmarked is an environment without the mark or a seat's tag, Python's owner.unmarked: what
// ak starts to outlive it.
func Unmarked(env []string) []string {
	var kept []string
	for _, pair := range env {
		if !strings.HasPrefix(pair, "AK_OWNER=") && !strings.HasPrefix(pair, "AK_TMUX_OWNER=") {
			kept = append(kept, pair)
		}
	}
	return kept
}
