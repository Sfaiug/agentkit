//go:build unix

package fetch

import (
	"errors"
	"os"
	"syscall"
)

// lockServe holds path's flock until the file closes, as Python ak's serve does.
func lockServe(path string) (*os.File, error) {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		file.Close()
		if errors.Is(err, syscall.EWOULDBLOCK) {
			return nil, errHeld
		}
		return nil, &os.PathError{Op: "flock", Path: path, Err: err}
	}
	return file, nil
}
