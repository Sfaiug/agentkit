package host

import (
	"os/exec"

	"golang.org/x/sys/windows"
)

// Group is how to stop cmd: Windows runs ak in WSL2 first, where a check's children go with it.
func Group(cmd *exec.Cmd) (stop func()) {
	return func() { cmd.Process.Kill() }
}

// Reap is whether the process cmd started has ended, waiting for its end if wait, and its exit
// code: the handle Go holds keeps its number its own until then.
func Reap(cmd *exec.Cmd, wait bool) (ended bool, code int, err error) {
	if !wait {
		process, err := windows.OpenProcess(windows.SYNCHRONIZE, false, uint32(cmd.Process.Pid))
		if err != nil {
			return true, 0, err
		}
		defer windows.CloseHandle(process)
		switch event, err := windows.WaitForSingleObject(process, 0); {
		case err != nil:
			return true, 0, err
		case event != windows.WAIT_OBJECT_0:
			return false, 0, nil
		}
	}
	state, err := cmd.Process.Wait()
	if err != nil {
		return true, 0, err
	}
	return true, state.ExitCode(), nil
}
