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
)

// What a slice's drop-ins set, as Python's orch reads them, and the one way a tick changes the runs
// slice; what the kernel says of them is readings.go's.

// ErrNoAnswer is a systemctl that did not answer within 5 seconds.
var ErrNoAnswer = errors.New("systemctl did not answer")

// SetOnRuns sets one property of the runs slice for this boot only, and is systemctl's exit code.
func SetOnRuns(property string) (int, error) {
	return setProperty(filepath.Base(RunsCgroup()), property)
}

// setProperty sets one property of a unit for this boot only, as Python's gc.systemctl runs
// `systemctl --user`, and is systemctl's exit code.
func setProperty(unit, property string) (int, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, "systemctl", "--user", "set-property", "--runtime", unit, property)
	command.Env = busEnv(os.Environ())
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

// busEnv is env with the user manager's bus in it, Python's orch.bus_env: a tick from cron has no
// session, and a caller's own says where its manager is.
func busEnv(env []string) []string {
	lookup := func(key string) (found string, set bool) {
		for _, pair := range env { // the last of a name, the one exec hands on
			if name, value, _ := strings.Cut(pair, "="); name == key {
				found, set = value, true
			}
		}
		return found, set
	}
	runtime, set := lookup("XDG_RUNTIME_DIR")
	if !set {
		runtime = fmt.Sprintf("/run/user/%d", os.Getuid())
		env = append(env, "XDG_RUNTIME_DIR="+runtime)
	}
	if _, set := lookup("DBUS_SESSION_BUS_ADDRESS"); !set {
		env = append(env, "DBUS_SESSION_BUS_ADDRESS=unix:path="+runtime+"/bus")
	}
	return env
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
