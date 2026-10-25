//go:build unix

package host

import (
	"errors"
	"os"
	"syscall"
)

// held is whether another process holds that turn file's lock now; the file is never made.
func held(path string) bool {
	file, err := os.Open(path)
	if err != nil {
		return false
	}
	defer file.Close()
	return errors.Is(syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB), syscall.EWOULDBLOCK)
}
