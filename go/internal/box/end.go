//go:build linux

package box

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"strconv"
	"strings"
	"syscall"
	"time"

	"agentkit/internal/config"
)

// stopFD is the descriptor the box's first process reads ak's stop by: its end, as ak closes its
// own or ends, asks the first process to end the command.
const stopFD = 4

// grace is how long the command has after TERM, as a harness saves its session, before what is
// left of it ends: Python's KILL_GRACE.
const grace = 5 * time.Second

// supervise waits for the command, a session's leader, reaping meanwhile the orphans a PID 1
// inherits: how it ended, and every other process still running in the box then, by pid, with
// its command line, which the first process's exit ends.  Asked by ak to stop, it gives the
// command's process group TERM; a command still running after grace ends by KILL with the rest.
func supervise(command int) (int, map[int]string) {
	ended := make(chan int, 1)
	go func() {
		for {
			var how syscall.WaitStatus
			pid, err := syscall.Wait4(-1, &how, 0, nil)
			if pid == command {
				ended <- status(how)
			} else if errors.Is(err, syscall.ECHILD) {
				return
			}
		}
	}()
	stop := make(chan struct{})
	go func() {
		io.Copy(io.Discard, os.NewFile(stopFD, "stop"))
		close(stop)
	}()
	var late <-chan time.Time
	for {
		select {
		case code := <-ended:
			return code, leftovers(command)
		case <-stop:
			stop, late = nil, time.After(grace)
			syscall.Kill(-command, syscall.SIGTERM)
		case <-late:
			return -int(syscall.SIGKILL), leftovers(command)
		}
	}
}

// leftovers is every process in the box but its first and the command, by pid, with its command
// line, as Python's box._supervise names them: one that has ended is none.
func leftovers(command int) map[int]string {
	left := map[int]string{}
	entries, _ := os.ReadDir("/proc")
	for _, entry := range entries {
		pid, err := strconv.Atoi(entry.Name())
		if err != nil || pid == os.Getpid() || pid == command {
			continue
		}
		stat, _ := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
		state := strings.Fields(string(stat[bytes.LastIndexByte(stat, ')')+1:]))
		if len(state) == 0 || state[0] == "Z" || state[0] == "X" {
			continue
		}
		said, err := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", pid))
		if errors.Is(err, fs.ErrNotExist) {
			continue
		} else if err != nil {
			said = []byte("command unavailable")
		}
		left[pid] = strings.TrimFunc(strings.ReplaceAll(string(said), "\x00", " "), config.Space)
	}
	return left
}
