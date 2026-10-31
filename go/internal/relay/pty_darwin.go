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

// wait is poll(2) on fds, without end.
func wait(fds []pollFd) error {
	forever := -1
	if _, _, errno := syscall.Syscall(syscall.SYS_POLL, uintptr(unsafe.Pointer(&fds[0])), uintptr(len(fds)), uintptr(forever)); errno != 0 {
		return errno
	}
	return nil
}
