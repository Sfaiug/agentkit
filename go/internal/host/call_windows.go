package host

import "os/exec"

// AdapterCall is how to stop cmd: Windows runs ak in WSL2 first, where an adapter's children go with it.
func AdapterCall(cmd *exec.Cmd) (stop func()) {
	return func() { cmd.Process.Kill() }
}
