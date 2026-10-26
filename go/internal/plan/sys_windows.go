package plan

import "os/exec"

// group is how to stop cmd: Windows runs ak in WSL2 first, where a check's children go with it.
func group(cmd *exec.Cmd) (stop func()) {
	return func() { cmd.Process.Kill() }
}

// lock takes no lock: no Python ak writes a plan beside native Windows ak.
func lock(string) (unlock func(), err error) {
	return func() {}, nil
}
