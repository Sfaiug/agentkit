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
	how := syscall.LOCK_EX
	if !wait {
		how |= syscall.LOCK_NB
	}
	return opened(path, how)
}

// Shared takes path's lock beside any other shared holder, once no exclusive one holds it, as
// Python's fcntl.LOCK_SH; a missing file is made, and the lock lasts until the file closes.
func Shared(path string) (*os.File, error) {
	return opened(path, syscall.LOCK_SH)
}

// tries is Wait's: path opened once, as acquire opens it, and each try a flock that does not wait
// on that one file, held open between them as a waiting flock holds it; stop closes it.
func tries(path string) (try func() (*os.File, error), stop func(), err error) {
	file, err := lockable(path)
	if err != nil {
		return nil, nil, err
	}
	return func() (*os.File, error) {
		if err := flock(file, syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
			if !errors.Is(err, ErrHeld) {
				file.Close()
			}
			return nil, err
		}
		return file, nil
	}, func() { file.Close() }, nil
}

// opened opens path, a directory to read and a file to append to, and takes its flock as how says.
func opened(path string, how int) (*os.File, error) {
	file, err := lockable(path)
	if err != nil {
		return nil, err
	}
	return take(file, how)
}

// lockable opens path, a directory to read and a file to append to, which it makes.
func lockable(path string) (*os.File, error) {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if errors.Is(err, syscall.EISDIR) {
		return os.Open(path)
	}
	return file, err
}

// Edit opens path's file, which it never makes, to read and write once its flock is free; the
// lock lasts until the file closes.
func Edit(path string) (*os.File, error) {
	file, err := os.OpenFile(path, os.O_RDWR, 0)
	if err != nil {
		return nil, err
	}
	return take(file, syscall.LOCK_EX)
}

// Read opens path's file, which it never makes, to read beside any other reader once no exclusive
// holder has its flock, as Python's fcntl.LOCK_SH; the lock lasts until the file closes.
func Read(path string) (*os.File, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	return take(file, syscall.LOCK_SH)
}

// take takes the open file's flock as how says; the file is closed without it.
func take(file *os.File, how int) (*os.File, error) {
	if err := flock(file, how); err != nil {
		file.Close()
		return nil, err
	}
	return file, nil
}

// flock takes the open file's flock as how says: ErrHeld where how does not wait and another
// holds it.
func flock(file *os.File, how int) error {
	var err error
	for err = syscall.EINTR; errors.Is(err, syscall.EINTR); {
		err = syscall.Flock(int(file.Fd()), how)
	}
	switch {
	case err == nil:
		return nil
	case errors.Is(err, syscall.EWOULDBLOCK):
		return ErrHeld
	default:
		return &os.PathError{Op: "flock", Path: file.Name(), Err: err}
	}
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
