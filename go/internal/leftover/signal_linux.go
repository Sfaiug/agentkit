//go:build linux && !(mips || mipsle || mips64 || mips64le)

package leftover

import "syscall"

// pidfd_open and pidfd_send_signal, numbered alike on every Linux but MIPS; Go's syscall
// package names neither.
const pidfdOpen, pidfdSendSignal = 434, 424

// signal sends number to the process at pid only if it started at start, Python's owner._send: a
// pidfd holds the process the pid named as it opened, and while the pid names one with that
// start, the held one is it. Without a pidfd nothing is sent, as a pid alone may name another
// process by the time the signal goes.
func signal(pid int, start int64, number syscall.Signal) bool {
	held, _, errno := syscall.Syscall(pidfdOpen, uintptr(pid), 0, 0)
	if errno != 0 {
		return false
	}
	defer syscall.Close(int(held))
	if stat, ok := readStat(pid); !ok || stat.Start != start {
		return false
	}
	_, _, errno = syscall.Syscall6(pidfdSendSignal, held, uintptr(number), 0, 0, 0, 0)
	return errno == 0
}
