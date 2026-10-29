//go:build unix

package lock

import (
	"errors"
	"os"
	"syscall"
)

// acquire opens path, a directory to read and a file to append to, and takes its flock, waiting
// for it or not.
func acquire(path string, wait bool) (*os.File, error) {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if errors.Is(err, syscall.EISDIR) {
		file, err = os.Open(path)
	}
	if err != nil {
		return nil, err
	}
	how := syscall.LOCK_EX
	if !wait {
		how |= syscall.LOCK_NB
	}
	for err = syscall.EINTR; errors.Is(err, syscall.EINTR); {
		err = syscall.Flock(int(file.Fd()), how)
	}
	if err != nil {
		file.Close()
		if errors.Is(err, syscall.EWOULDBLOCK) {
			return nil, ErrHeld
		}
		return nil, &os.PathError{Op: "flock", Path: path, Err: err}
	}
	return file, nil
}

// Held is whether another holder has path's lock now; the file is never made.
func Held(path string) bool {
	file, err := os.Open(path)
	if err != nil {
		return false
	}
	defer file.Close()
	return errors.Is(syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB), syscall.EWOULDBLOCK)
}
