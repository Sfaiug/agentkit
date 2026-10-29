package lock

import (
	"os"
	"syscall"
	"time"
)

const errorSharingViolation = syscall.Errno(32)

// acquire opens path shared with nobody, waiting its turn or not; a directory is opened with
// no lock.
func acquire(path string, wait bool) (*os.File, error) {
	if info, err := os.Stat(path); err == nil && info.IsDir() {
		return os.Open(path)
	}
	name, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	for {
		handle, err := syscall.CreateFile(name, syscall.GENERIC_WRITE, 0, nil, syscall.OPEN_ALWAYS, syscall.FILE_ATTRIBUTE_NORMAL, 0)
		if err == nil {
			return os.NewFile(uintptr(handle), path), nil
		}
		if err != errorSharingViolation {
			return nil, &os.PathError{Op: "open", Path: path, Err: err}
		}
		if !wait {
			return nil, ErrHeld
		}
		time.Sleep(10 * time.Millisecond)
	}
}

// Held is whether another holder has path open shared with nobody now; the file is never made.
func Held(path string) bool {
	name, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return false
	}
	handle, err := syscall.CreateFile(name, syscall.GENERIC_READ, 0, nil, syscall.OPEN_EXISTING, syscall.FILE_ATTRIBUTE_NORMAL, 0)
	if err == nil {
		syscall.CloseHandle(handle)
	}
	return err == errorSharingViolation
}
