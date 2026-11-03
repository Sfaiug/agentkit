package terminal

import "syscall"

// TCSETSW, which Go's syscall leaves out: TCSETS that waits for what was written to go out.
const getAttrs, setAttrs = syscall.TCGETS, syscall.TCSETS + 1

func selected(top int, set *syscall.FdSet, limit *syscall.Timeval) error {
	_, err := syscall.Select(top, set, nil, nil, limit)
	return err
}
