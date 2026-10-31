//go:build linux

package box

import (
	"cmp"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"agentkit/internal/config"
)

// install puts bubblewrap on a host.
const install = "sudo apt-get install -y bubblewrap"

// Check is why this host cannot start a worker's box, or nil: what building one refuses, or a
// box for `true` that fails inside a second box, both built as a turn's is, which bubblewrap's
// words or exit status and the remedy say.  A probe still running after 10 seconds is a loaded
// host, as one that cannot nest a box says so at once, and every turn keeps its own limits.
func Check() error {
	env := map[string]string{}
	for _, pair := range os.Environ() {
		key, value, _ := strings.Cut(pair, "=")
		env[key] = value
	}
	probe, err := os.MkdirTemp("", "ak-box-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(probe)
	inner, done, err := command([]string{"true"}, env, probe, probe, nil, nil, nil)
	if err != nil {
		return err
	}
	defer done()
	outer, done, err := command(inner.Args, env, probe, probe, nil, nil, nil)
	if err != nil {
		return err
	}
	defer done()
	var said strings.Builder
	outer.Stderr = &said
	if err := outer.Start(); err != nil {
		return err
	}
	late := time.AfterFunc(10*time.Second, func() { outer.Process.Kill() })
	err = outer.Wait()
	exit := &exec.ExitError{}
	if !late.Stop() || !errors.As(err, &exit) {
		return nil
	}
	why := cmp.Or(strings.TrimFunc(said.String(), config.Space), fmt.Sprintf("exit %d", status(exit.Sys().(syscall.WaitStatus))))
	return fmt.Errorf("worker box cannot start: %s; run `%s`; the host must allow nested unprivileged user and PID namespaces", why, remedy())
}

// remedy is the command opening the first kernel setting that keeps a box from nesting, or else
// the one installing bubblewrap.
func remedy() string {
	for _, setting := range [][3]string{{"unprivileged_userns_clone", "0", "1"}, {"apparmor_restrict_unprivileged_userns", "1", "0"}} {
		if value, err := os.ReadFile(filepath.Join("/proc/sys/kernel", setting[0])); err == nil && strings.TrimSpace(string(value)) == setting[1] {
			return fmt.Sprintf("sudo sysctl -w kernel.%s=%s", setting[0], setting[2])
		}
	}
	return install
}
