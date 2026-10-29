//go:build unix

package plan

import (
	"os/exec"
	"syscall"
)

// group starts cmd in a session of its own and is how to stop it, every child it started with it.
func group(cmd *exec.Cmd) (stop func()) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	stop = func() { syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) }
	cmd.Cancel = func() error { stop(); return nil }
	return stop
}
