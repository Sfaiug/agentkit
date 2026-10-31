package host

import (
	"bytes"
	"errors"
	"os"
	"runtime"
	"strconv"
	"strings"
	"syscall"
)

// clockTicks is USER_HZ, the unit of a start time in /proc/<pid>/stat: 100 on every Linux
// build ak runs on, and Go's standard library has no sysconf to ask.
const clockTicks = 100

// Alive says only whether the process exists; owning a run also takes its identity.
func Alive(pid int) bool {
	if pid <= 0 {
		return false
	}
	process, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	err = process.Signal(syscall.Signal(0))
	return err == nil || errors.Is(err, os.ErrPermission) || runtime.GOOS == "windows"
}

// A Stat is what ak reads of /proc/<pid>/stat: the state letter, the parent, the kernel's flags
// and the start in clock ticks.
type Stat struct {
	State  string
	Parent int
	Flags  int
	Start  int64
}

// Exited is a zombie or a dead task: it runs nothing, though it may still answer kill(0).
func (s Stat) Exited() bool {
	return s.State == "Z" || s.State == "X"
}

// ReadStat counts the fields after the last `)`, as the command name may hold spaces or `)`.
func ReadStat(pid int) (Stat, bool) {
	data, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/stat")
	at := bytes.LastIndexByte(data, ')')
	if err != nil || at < 0 {
		return Stat{}, false
	}
	fields := strings.Fields(string(data[at+1:]))
	if len(fields) < 20 {
		return Stat{}, false
	}
	parent, err := strconv.Atoi(fields[1])
	flags, unread := strconv.Atoi(fields[6])
	start, failed := strconv.ParseInt(fields[19], 10, 64)
	if err != nil || unread != nil || failed != nil {
		return Stat{}, false
	}
	return Stat{State: fields[0], Parent: parent, Flags: flags, Start: start}, true
}

// An Identity is a process's birth, with the boot, so a reboot cannot recycle one.
type Identity struct {
	Boot      string
	Ticks     int64
	StartedAt float64
}

func ReadIdentity(pid int) (Identity, bool) {
	stat, ok := ReadStat(pid)
	if !ok || stat.Exited() {
		return Identity{}, false
	}
	boot, err := os.ReadFile("/proc/sys/kernel/random/boot_id")
	if err != nil {
		return Identity{}, false
	}
	data, err := os.ReadFile("/proc/stat")
	if err != nil {
		return Identity{}, false
	}
	for _, line := range strings.Split(string(data), "\n") {
		if fields := strings.Fields(line); len(fields) > 1 && fields[0] == "btime" {
			btime, err := strconv.ParseInt(fields[1], 10, 64)
			if err != nil {
				return Identity{}, false
			}
			return Identity{strings.TrimSpace(string(boot)), stat.Start,
				float64(btime) + float64(stat.Start)/clockTicks}, true
		}
	}
	return Identity{}, false
}

// Resident is a process's resident bytes from its statm.
func Resident(pid int) (int64, bool) {
	data, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/statm")
	fields := strings.Fields(string(data))
	if err != nil || len(fields) < 2 {
		return 0, false
	}
	pages, err := strconv.ParseInt(fields[1], 10, 64)
	return pages * int64(os.Getpagesize()), err == nil
}

// Marker is the variable every process of a run carries, its marker: the run's directory, and
// below it a part of the run, such as one turn.
const Marker = "AGENTKIT_RUN"

// Marked are the pids whose environment carries the run's marker, or one below it, except
// this process and its ancestors: found by environment, so a child that left its process
// group is still one of the run's.
func Marked(marker string) []int {
	want := []byte(Marker + "=" + marker)
	below := []byte(Marker + "=" + marker + "/")
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil
	}
	skip := map[int]bool{}
	for pid := os.Getpid(); pid > 0 && !skip[pid]; {
		skip[pid] = true
		stat, ok := ReadStat(pid)
		if !ok {
			break
		}
		pid = stat.Parent
	}
	var found []int
	for _, entry := range entries {
		pid, err := strconv.Atoi(entry.Name())
		if err != nil || skip[pid] {
			continue
		}
		environ, err := os.ReadFile("/proc/" + entry.Name() + "/environ")
		if err != nil {
			continue
		}
		for _, part := range bytes.Split(environ, []byte{0}) {
			if bytes.Equal(part, want) || bytes.HasPrefix(part, below) {
				found = append(found, pid)
				break
			}
		}
	}
	return found
}
