//go:build unix

package host

import (
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
)

// Group starts cmd in a session of its own and is how to stop it, with everything still in that
// session, as Python's config._end ends an adapter call: a child leading a group of its own
// (`timeout` makes one) goes too, and only one gone to a session of its own, a service started on
// purpose, stays.  The session's id names no other while a member is left, so stopping after the
// wait finds only what the command left behind.
func Group(cmd *exec.Cmd) (stop func()) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	stop = func() {
		session := cmd.Process.Pid
		syscall.Kill(-session, syscall.SIGKILL)
		for _, pid := range processes() {
			if sid, err := getsid(pid); err == nil && sid == session {
				if group, err := syscall.Getpgid(pid); err == nil {
					syscall.Kill(-group, syscall.SIGKILL)
				}
				syscall.Kill(pid, syscall.SIGKILL)
			}
		}
	}
	cmd.Cancel = func() error { stop(); return nil }
	return stop
}

// processes is every process's pid: /proc's, or `ps`'s where there is none (macOS).
func processes() []int {
	var names []string
	if entries, err := os.ReadDir("/proc"); err == nil {
		for _, entry := range entries {
			names = append(names, entry.Name())
		}
	} else if out, err := exec.Command("ps", "-A", "-o", "pid=").Output(); err == nil {
		names = strings.Fields(string(out))
	}
	var pids []int
	for _, name := range names {
		if pid, err := strconv.Atoi(name); err == nil {
			pids = append(pids, pid)
		}
	}
	return pids
}
