package host

import (
	"fmt"
	"os"
	"strings"
)

// Mark marks this process, and so everything it starts, as name's, Python's owner.mark: AK_OWNER
// is `<pid namespace> <pid> <start> <session> <name>`, the namespace by its inode, so what an
// `ak` leaves running is told apart once it is gone, and what ak starts to outlive it goes
// without.  A seat's tag on a side session (AK_TMUX_OWNER) goes first: no start of ak's is the
// seat's.  Where /proc cannot say, the mark inherited, if any, stays.
func Mark(name string) {
	os.Unsetenv("AK_TMUX_OWNER")
	link, _ := os.Readlink("/proc/self/ns/pid") // `pid:[<inode>]`
	inode, named := strings.CutPrefix(strings.TrimSuffix(link, "]"), "pid:[")
	if stat, ok := ReadStat(os.Getpid()); ok && named {
		os.Setenv("AK_OWNER", fmt.Sprintf("%s %d %d %d %s", inode, os.Getpid(), stat.Start, stat.Session, name))
	}
}
