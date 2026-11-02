package host

import (
	"io"
	"syscall"
)

// EndMarked ends nothing: no process is found by its environment here.
func EndMarked(string, io.Writer) {}

// Detached is nothing more than a plain start here.
func Detached() *syscall.SysProcAttr { return nil }

// Lower is nothing here.
func Lower() {}
