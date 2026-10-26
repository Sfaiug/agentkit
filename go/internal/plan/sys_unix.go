//go:build unix

package plan

import (
	"os"
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

// lock holds path's flock, as Python ak's writers take it, until unlock.
func lock(path string) (unlock func(), err error) {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX); err != nil {
		file.Close()
		return nil, &os.PathError{Op: "flock", Path: path, Err: err}
	}
	return func() { file.Close() }, nil
}
