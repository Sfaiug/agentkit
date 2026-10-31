package host

import "os/exec"

// Group is how to stop cmd: Windows runs ak in WSL2 first, where a check's children go with it.
func Group(cmd *exec.Cmd) (stop func()) {
	return func() { cmd.Process.Kill() }
}
