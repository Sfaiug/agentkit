//go:build unix

package host

import (
	"os/exec"
	"syscall"
)

// Term asks the group a command started by Group leads to end, as Python's os.killpg does with
// SIGTERM: a shim's child goes with it.
func Term(cmd *exec.Cmd) {
	syscall.Kill(-cmd.Process.Pid, syscall.SIGTERM)
}
