package relay

import (
	"fmt"
	"os"
	"syscall"
	"unsafe"
)

// a terminal's modes, read and set at once
const get, set = syscall.TCGETS, syscall.TCSETS

// unlock opens the program's end of a new pty, and answers its path.
func unlock(master *os.File) (string, error) {
	var locked int32
	var number uint32
	if err := ioctl(master, syscall.TIOCSPTLCK, unsafe.Pointer(&locked)); err != nil {
		return "", err
	}
	if err := ioctl(master, syscall.TIOCGPTN, unsafe.Pointer(&number)); err != nil {
		return "", err
	}
	return fmt.Sprintf("/dev/pts/%d", number), nil
}

// wait is poll(2) on fds, without end: ppoll, as arm64 has no poll.
func wait(fds []pollFd) error {
	if _, _, errno := syscall.Syscall6(syscall.SYS_PPOLL, uintptr(unsafe.Pointer(&fds[0])), uintptr(len(fds)), 0, 0, 0, 0); errno != 0 {
		return errno
	}
	return nil
}
