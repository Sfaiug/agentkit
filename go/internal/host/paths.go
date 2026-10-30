package host

import (
	"bytes"
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
		if _, err := strconv.Atoi(entry.Name()); err != nil {
			continue
		}
		proc := "/proc/" + entry.Name()
		named, err := held(proc)
		if err != nil {
			if _, err := os.Stat(proc); errors.Is(err, fs.ErrNotExist) {
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
func held(proc string) ([]string, error) {
	fields, err := stat(proc)
	if err != nil {
		return nil, err
	}
	flags, err := strconv.Atoi(fields[6])
	if err != nil {
		return nil, err
	}
	if fields[0] == "Z" || fields[0] == "X" || flags&0x200000 != 0 { // PF_KTHREAD
		return nil, nil
	}
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
	if again, err := stat(proc); err != nil || again[19] != fields[19] {
		return nil, errors.New("pid was reused during the scan")
	}
	return paths, nil
}

// stat is the fields of a process's stat after its command's name, which may hold `)`.
func stat(proc string) ([]string, error) {
	data, err := os.ReadFile(proc + "/stat")
	if err != nil {
		return nil, err
	}
	fields := strings.Fields(string(data[bytes.LastIndexByte(data, ')')+1:]))
	if !bytes.Contains(data, []byte(")")) || len(fields) < 20 {
		return nil, errors.New(proc + "/stat is cut short")
	}
	return fields, nil
}
