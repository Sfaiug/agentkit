package run

import (
	"path/filepath"
	"syscall"
	"time"
)

const errorSharingViolation = syscall.Errno(32)

// hold opens the named file in the run's directory shared with nobody, waiting its turn; the
// directory's own lock is nothing here: Python ak never runs on Windows, so the named file's
// alone keeps writes apart.
func hold(dir, name string) (func(), error) {
	if name == "" {
		return func() {}, nil
	}
	path, err := syscall.UTF16PtrFromString(filepath.Join(dir, name))
	if err != nil {
		return nil, err
	}
	for {
		handle, err := syscall.CreateFile(path, syscall.GENERIC_WRITE, 0, nil, syscall.OPEN_ALWAYS, syscall.FILE_ATTRIBUTE_NORMAL, 0)
		if err == nil {
			return func() { syscall.CloseHandle(handle) }, nil
		}
		if err != errorSharingViolation {
			return nil, err
		}
		time.Sleep(10 * time.Millisecond)
	}
}
