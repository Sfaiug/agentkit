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

// Check is why this host cannot start a worker's box, or nil: what building one refuses, else a
// box for `true` inside a second box, each built by the code a turn's is, failing with why
// bubblewrap did not start or its words or exit status, which the remedy follows.  A probe still
// running after 10 seconds is a loaded host, not one that cannot nest a box, which says so at
// once; every turn keeps its own limits.  No room to start a process is the host's for a moment,
// not a box it cannot build.
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
	inner, done, err := command([]string{"true"}, env, "", probe, nil, nil, nil)
	if err != nil {
		return err
	}
	defer done()
	outer, done, err := command(inner.Args, env, "", probe, nil, nil, nil)
	if err != nil {
		return err
	}
	defer done()
	// A file, not a pipe: a child the probe leaves holding its stderr holds up no wait.
	said, err := os.Create(filepath.Join(probe, "stderr"))
	if err != nil {
		return err
	}
	defer said.Close()
	outer.Stderr = said
	if err := outer.Start(); errors.Is(err, syscall.EAGAIN) {
		return err
	} else if err != nil {
		return cannot(err.Error())
	}
	late := time.AfterFunc(10*time.Second, func() { outer.Process.Kill() })
	err = outer.Wait()
	exit := &exec.ExitError{}
	if !late.Stop() || !errors.As(err, &exit) {
		return nil
	}
	words, err := os.ReadFile(said.Name())
	if err != nil {
		return err
	}
	return cannot(cmp.Or(strings.TrimFunc(string(words), config.Space), fmt.Sprintf("exit %d", status(exit.Sys().(syscall.WaitStatus)))))
}

// cannot is the refusal of a probe that failed for why, with the command opening the first kernel
// setting that keeps a box from nesting, or else the one installing bubblewrap.
func cannot(why string) error {
	remedy := install
	for _, setting := range [][3]string{{"unprivileged_userns_clone", "0", "1"}, {"apparmor_restrict_unprivileged_userns", "1", "0"}} {
		if value, err := os.ReadFile(filepath.Join("/proc/sys/kernel", setting[0])); err == nil && strings.TrimSpace(string(value)) == setting[1] {
			remedy = fmt.Sprintf("sudo sysctl -w kernel.%s=%s", setting[0], setting[2])
			break
		}
	}
	return fmt.Errorf("worker box cannot start: %s; run `%s`; the host must allow nested unprivileged user and PID namespaces", why, remedy)
}
