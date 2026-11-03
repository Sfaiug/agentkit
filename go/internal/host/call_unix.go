//go:build unix

package host

import (
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// AdapterCall has cmd start as Python's config.run_adapter starts an adapter call: in a process
// group of its own, in ak's session, so what it leaves there is the leftover sweep's once this ak
// is gone, and what it starts in a session of its own, a harness's own service, runs on. stop,
// which a cancelled context calls too, is Python's _end: KILL to each process of the call's tree
// still in ak's session and each group one of those leads (`timeout` makes one), then up to a
// second for them to go. What has left the call's tree by then is the sweep's.
func AdapterCall(cmd *exec.Cmd) (stop func()) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	stop = func() {
		parents, below := parentsOf(), map[int][]int{}
		for child, parent := range parents {
			below[parent] = append(below[parent], child)
		}
		session, _ := getsid(0)
		killed, groups := map[int]bool{}, map[int]bool{}
		for stack := []int{cmd.Process.Pid}; len(stack) > 0; {
			pid := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			if sid, err := getsid(pid); killed[pid] || err != nil || sid != session {
				continue
			}
			killed[pid] = true
			stack = append(stack, below[pid]...)
			if group, err := syscall.Getpgid(pid); err == nil && group == pid {
				groups[pid] = true
			}
		}
		for group := range groups {
			syscall.Kill(-group, syscall.SIGKILL)
		}
		for pid := range killed {
			syscall.Kill(pid, syscall.SIGKILL)
		}
		for other := range parents {
			if group, err := syscall.Getpgid(other); err == nil && groups[group] {
				killed[other] = true
			}
		}
		for late := time.Now().Add(time.Second); time.Now().Before(late); time.Sleep(10 * time.Millisecond) {
			running := parentsOf()
			if !anyIn(killed, running) {
				return
			}
		}
	}
	cmd.Cancel = func() error { stop(); return nil }
	return stop
}

func anyIn(pids map[int]bool, running map[int]int) bool {
	for pid := range pids {
		if _, ok := running[pid]; ok {
			return true
		}
	}
	return false
}

// parentsOf is the parent of every process still running, by pid, Python's host.parents: from
// /proc, or `ps` where there is none (macOS).
func parentsOf() map[int]int {
	parents := map[int]int{}
	if entries, err := os.ReadDir("/proc"); err == nil {
		for _, entry := range entries {
			if pid, err := strconv.Atoi(entry.Name()); err == nil {
				if stat, ok := ReadStat(pid); ok && !stat.Exited() {
					parents[pid] = stat.Parent
				}
			}
		}
		return parents
	}
	out, _ := exec.Command("ps", "-A", "-o", "pid=", "-o", "ppid=", "-o", "stat=").Output()
	for _, line := range strings.Split(string(out), "\n") {
		words := strings.Fields(line)
		if len(words) != 3 || strings.ContainsAny(words[2][:1], "ZX") {
			continue
		}
		pid, err := strconv.Atoi(words[0])
		parent, unread := strconv.Atoi(words[1])
		if err == nil && unread == nil {
			parents[pid] = parent
		}
	}
	return parents
}
