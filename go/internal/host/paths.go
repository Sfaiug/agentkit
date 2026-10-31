package host

import (
	"errors"
	"io/fs"
	"os"
	"strconv"
	"strings"
)

// Held is every path a process here names, as Python's gc.tmp_processes reads them: each
// absolute word of its command line, its working directory and each file it holds open.  ok is
// false where that proves nothing idle: no /proc, or a process that hides its own from this user,
// which Python asks `sudo -n` to read.
func Held() (paths []string, ok bool) {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil, false
	}
	for _, entry := range entries {
		pid, err := strconv.Atoi(entry.Name())
		if err != nil {
			continue
		}
		named, err := held(pid)
		if err != nil {
			if _, err := os.Stat("/proc/" + entry.Name()); errors.Is(err, fs.ErrNotExist) {
				continue // it exited
			}
			return nil, false
		}
		paths = append(paths, named...)
	}
	return paths, true
}

// held is what one process names, nothing for a zombie or a kernel thread; an error where any of
// it could not be read, or the pid named another process by the end.
func held(pid int) ([]string, error) {
	first, ok := ReadStat(pid)
	if !ok {
		return nil, errors.New("no stat to read")
	}
	if first.Exited() || first.Flags&0x200000 != 0 { // PF_KTHREAD
		return nil, nil
	}
	proc := "/proc/" + strconv.Itoa(pid)
	cmdline, err := os.ReadFile(proc + "/cmdline")
	if err != nil {
		return nil, err
	}
	var paths []string
	for _, arg := range strings.Split(string(cmdline), "\x00") {
		if strings.HasPrefix(arg, "/") {
			paths = append(paths, arg)
		}
	}
	cwd, err := os.Readlink(proc + "/cwd")
	if err != nil {
		return nil, err
	}
	links := []string{cwd}
	fds, err := os.ReadDir(proc + "/fd")
	if err != nil {
		return nil, err
	}
	for _, fd := range fds {
		target, err := os.Readlink(proc + "/fd/" + fd.Name())
		if errors.Is(err, fs.ErrNotExist) {
			continue // closed since
		}
		if err != nil {
			return nil, err
		}
		links = append(links, target)
	}
	for _, target := range links {
		if strings.HasPrefix(target, "/") {
			paths = append(paths, target, strings.TrimSuffix(target, " (deleted)"))
		}
	}
	if again, ok := ReadStat(pid); !ok || again.Start != first.Start {
		return nil, errors.New("pid was reused during the scan")
	}
	return paths, nil
}
