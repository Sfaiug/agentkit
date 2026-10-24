package fetch

import (
	"os"
	"syscall"
)

const errorSharingViolation = syscall.Errno(32)

// lockServe opens path shared with nobody, so a second connection's open fails until the file closes.
func lockServe(path string) (*os.File, error) {
	name, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	handle, err := syscall.CreateFile(name, syscall.GENERIC_WRITE, 0, nil, syscall.OPEN_ALWAYS, syscall.FILE_ATTRIBUTE_NORMAL, 0)
	if err == errorSharingViolation {
		return nil, errHeld
	}
	if err != nil {
		return nil, &os.PathError{Op: "open", Path: path, Err: err}
	}
	return os.NewFile(uintptr(handle), path), nil
}
