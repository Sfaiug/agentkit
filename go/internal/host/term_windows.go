package host

import "os/exec"

// Term is Group's stop: Windows asks no process to end.
func Term(cmd *exec.Cmd) {
	cmd.Process.Kill()
}
