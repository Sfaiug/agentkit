//go:build unix && !linux

package tick

import (
	"os"
	"syscall"
)

// dup points stream's descriptor at from's file.
func dup(from, stream *os.File) {
	syscall.Dup2(int(from.Fd()), int(stream.Fd()))
}
