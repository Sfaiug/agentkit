package tick

import (
	"os"
	"syscall"
)

// dup points stream's descriptor at from's file; Linux on arm64 has dup3 and no dup2.
func dup(from, stream *os.File) {
	syscall.Dup3(int(from.Fd()), int(stream.Fd()), 0)
}
