//go:build unix

package host

import (
	"os/exec"
	"syscall"
)

// Detach has cmd start in a session of its own, so whoever starts it ends none of it by ending.
func Detach(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}
