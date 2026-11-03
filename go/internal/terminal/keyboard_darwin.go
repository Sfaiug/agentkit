package terminal

import "syscall"

const getAttrs, setAttrs = syscall.TIOCGETA, syscall.TIOCSETAW

func selected(top int, set *syscall.FdSet, limit *syscall.Timeval) error {
	return syscall.Select(top, set, nil, nil, limit)
}
