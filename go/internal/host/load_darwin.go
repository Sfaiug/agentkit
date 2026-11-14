package host

import (
	"encoding/binary"

	"golang.org/x/sys/unix"
)

// loadAverage is the one-minute load macOS keeps, as its getloadavg(3) reads it: sysctl
// vm.loadavg is a struct loadavg, three 32-bit fixed-point loads, then at offset 16 their scale.
func loadAverage() (float64, bool) {
	raw, err := unix.SysctlRaw("vm.loadavg")
	if err != nil || len(raw) < 24 {
		return 0, false
	}
	scale := binary.NativeEndian.Uint64(raw[16:])
	return float64(binary.NativeEndian.Uint32(raw)) / float64(scale), scale != 0
}
