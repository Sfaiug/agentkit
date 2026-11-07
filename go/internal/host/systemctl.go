package host

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"
)

const answer = 5 * time.Second // what a systemctl has to answer in, as Python's gc.systemd waits

// ErrNoAnswer is a systemctl that did not answer within 5 seconds.
var ErrNoAnswer = errors.New("systemctl did not answer")

// Systemctl is `systemctl --user ARGS` as Python's gc.systemctl runs it: its exit code and what it
// printed. Every call Go makes to the user manager goes through it, and tests replace it.
var Systemctl = func(args ...string) (int, string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), answer)
	defer cancel()
	command := exec.CommandContext(ctx, "systemctl", append([]string{"--user"}, args...)...)
	var out strings.Builder
	command.Env, command.Stdout = busEnv(os.Environ()), &out
	command.WaitDelay = answer // a program it left holding its output open is waited for no longer
	err := command.Run()
	var exited *exec.ExitError
	switch {
	case ctx.Err() != nil:
		return 0, "", ErrNoAnswer
	case errors.As(err, &exited):
		return exited.ExitCode(), out.String(), nil
	}
	return 0, out.String(), err
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
