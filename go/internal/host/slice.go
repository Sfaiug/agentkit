package host

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/tmux"
)

// What ak's slice says of its ceilings and what its runs and seats hold, as Python's orch and host
// read them, and the one way a tick changes the runs slice.

// SliceMemory is ak's slice's MemoryMax in MiB and what the slice holds outside its runs, cache
// included, as MemoryMax counts it; false where no drop-in sets a ceiling or the slice's memory is
// unread. The ceiling is the drop-ins', real before the slice's first process.
func SliceMemory() (ceiling, seats int, ok bool) {
	ceiling, set := dropInMemoryMax(tmux.Own() + ".slice")
	held, read := megabytes(filepath.Join(sliceCgroup(), "memory.current"))
	if !set || !read {
		return 0, 0, false
	}
	runs, _ := megabytes(filepath.Join(RunsCgroup(), "memory.current"))
	return ceiling, int(held - runs), true
}

// SliceTasks is ak's slice's task ceiling, the kernel's else its drop-ins', false where neither
// sets one.
func SliceTasks() (int, bool) {
	if ceiling, ok := tasksMax(sliceCgroup()); ok {
		return ceiling, true
	}
	return dropInTasksMax(tmux.Own() + ".slice")
}

// RunsTasks is the runs slice's TasksMax in its drop-ins, 0 where none names one, and the one
// the kernel holds, false where it holds none.
func RunsTasks() (dropIn, held int, holds bool) {
	dropIn, _ = dropInTasksMax(filepath.Base(RunsCgroup()))
	held, holds = tasksMax(RunsCgroup())
	return dropIn, held, holds
}

// OthersTasksPeak is the most tasks each child of ak's slice but the runs has held, added up: a
// child's peak counts what is under it. A pids.peak unread counts 0, as on a kernel without one.
func OthersTasksPeak() int {
	slice, runs, sum := sliceCgroup(), RunsCgroup(), 0
	for _, child := range config.Glob(slice, "*") {
		if peak, ok := number(filepath.Join(child, "pids.peak")); ok && child != runs {
			sum += int(peak)
		}
	}
	return sum
}

// ErrNoAnswer is a systemctl that did not answer within 5 seconds.
var ErrNoAnswer = errors.New("systemctl did not answer")

// SetOnRuns sets one property of the runs slice for this boot only, as Python's gc.systemctl runs
// `systemctl --user`, and is systemctl's exit code.
func SetOnRuns(property string) (int, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, "systemctl", "--user", "set-property", "--runtime",
		filepath.Base(RunsCgroup()), property)
	command.Env = busEnv()
	err := command.Run()
	var exited *exec.ExitError
	switch {
	case ctx.Err() != nil:
		return 0, ErrNoAnswer
	case errors.As(err, &exited):
		return exited.ExitCode(), nil
	}
	return 0, err
}

// busEnv is this environment with the user manager's bus in it, Python's orch.bus_env: a tick
// from cron has no session, and a caller's own says where its manager is.
func busEnv() []string {
	env := os.Environ()
	runtime, set := os.LookupEnv("XDG_RUNTIME_DIR")
	if !set {
		runtime = fmt.Sprintf("/run/user/%d", os.Getuid())
		env = append(env, "XDG_RUNTIME_DIR="+runtime)
	}
	if _, set := os.LookupEnv("DBUS_SESSION_BUS_ADDRESS"); !set {
		env = append(env, "DBUS_SESSION_BUS_ADDRESS=unix:path="+runtime+"/bus")
	}
	return env
}

// tasksMax is a cgroup's pids.max, false where it says `max` or is unread.
func tasksMax(cgroup string) (int, bool) {
	data, err := os.ReadFile(filepath.Join(cgroup, "pids.max"))
	text := strings.TrimFunc(string(data), config.Space)
	value, failed := strconv.Atoi(text)
	return value, err == nil && failed == nil && config.Digits(text)
}

// dropInTasksMax is the TasksMax a slice's drop-ins set, false where none does. The last file to
// name it wins, as systemd reads them.
func dropInTasksMax(slice string) (int, bool) {
	found, set := 0, false
	for _, value := range dropInValues(slice, "TasksMax") {
		if ceiling, err := strconv.Atoi(value); err == nil && config.Digits(value) {
			found, set = ceiling, true
		}
	}
	return found, set
}

var memorySpec = regexp.MustCompile(`(?i)^(\d+)([KMGT%]?)$`)

// dropInMemoryMax is the MemoryMax a slice's drop-ins set in MiB, false where none does or the
// last says `max` or `infinity`. A bare number is bytes; a percentage is of MemTotal.
func dropInMemoryMax(slice string) (int, bool) {
	found, set := 0, false
	for _, value := range dropInValues(slice, "MemoryMax") {
		if lower := strings.ToLower(value); lower == "max" || lower == "infinity" {
			found, set = 0, false
			continue
		}
		parts := memorySpec.FindStringSubmatch(value)
		if parts == nil {
			continue
		}
		number, err := strconv.Atoi(parts[1])
		if err != nil {
			continue
		}
		switch strings.ToUpper(parts[2]) {
		case "":
			found = number >> 20
		case "K":
			found = number >> 10
		case "M":
			found = number
		case "G":
			found = number << 10
		case "T":
			found = number << 20
		case "%":
			total, ok := memTotalMB()
			if !ok {
				continue
			}
			found = total * number / 100
		}
		set = true
	}
	return found, set
}

// memTotalMB is the host's MemTotal in whole MiB.
func memTotalMB() (int, bool) {
	data, _ := os.ReadFile("/proc/meminfo")
	for _, line := range strings.Split(string(data), "\n") {
		if rest, ok := strings.CutPrefix(line, "MemTotal:"); ok {
			if fields := strings.Fields(rest); len(fields) > 0 {
				kb, err := strconv.Atoi(fields[0])
				return kb / 1024, err == nil
			}
		}
	}
	return 0, false
}

// dropInValues are the values a slice's drop-ins give key, stripped, in the order systemd reads
// them.
func dropInValues(slice, key string) []string {
	var values []string
	for _, file := range dropIns(slice) {
		data, _ := os.ReadFile(file)
		for _, line := range strings.Split(string(data), "\n") {
			name, value, _ := strings.Cut(line, "=")
			if strings.TrimFunc(name, config.Space) == key {
				values = append(values, strings.TrimFunc(value, config.Space))
			}
		}
	}
	return values
}
