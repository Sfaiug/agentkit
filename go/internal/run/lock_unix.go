//go:build unix

package run

import (
	"os"
	"path/filepath"
	"syscall"
)

// hold waits for one of Python ak's locks on a run, held until release: the named file's in
// the run's directory, or with no name the directory's own.
func hold(dir, name string) (func(), error) {
	file, err := os.Open(dir)
	if name != "" {
		file, err = os.OpenFile(filepath.Join(dir, name), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0666)
	}
	if err != nil {
		return nil, err
	}
	for err = syscall.EINTR; err == syscall.EINTR; {
		err = syscall.Flock(int(file.Fd()), syscall.LOCK_EX)
	}
	if err != nil {
		file.Close()
		return nil, err
	}
	return func() { file.Close() }, nil
}
