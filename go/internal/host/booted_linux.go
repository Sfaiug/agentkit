package host

import (
	"time"

	"golang.org/x/sys/unix"
)

// booted is when this machine booted, on the wall clock: read off the boot clock a process's
// start is counted on, as /proc/stat's btime is whole seconds and makes a process up to a second
// older than it is, Python's host.process_age.  Go runs on no Linux without CLOCK_BOOTTIME.
func booted() float64 {
	var since unix.Timespec
	unix.ClockGettime(unix.CLOCK_BOOTTIME, &since)
	return float64(time.Now().UnixNano()-since.Nano()) / 1e9
}
