package relay

import (
	"bytes"
	"os"
	"syscall"
	"unsafe"
)

// a terminal's modes, read and set at once
const get, set = syscall.TIOCGETA, syscall.TIOCSETA

// unlock opens the program's end of a new pty, as grantpt and unlockpt do, and answers its path,
// as ptsname does.
func unlock(master *os.File) (string, error) {
	var path [128]byte
	if err := ioctl(master, syscall.TIOCPTYGRANT, nil); err != nil {
		return "", err
	}
	if err := ioctl(master, syscall.TIOCPTYUNLK, nil); err != nil {
		return "", err
	}
	if err := ioctl(master, syscall.TIOCPTYGNAME, unsafe.Pointer(&path)); err != nil {
		return "", err
	}
	name, _, _ := bytes.Cut(path[:], []byte{0})
	return string(name), nil
}

// wait is select(2) on what can be read.
func wait(n int, readable *syscall.FdSet) error {
	return syscall.Select(n, readable, nil, nil, nil)
}
