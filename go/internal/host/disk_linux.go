package host

import (
	"os"
	"strconv"
	"strings"

	"golang.org/x/sys/unix"
)

// diskReadings are the disk holding path and each virtiofs mount's free space, by the names
// DiskUse reads injected (host._disk_readings); none where path's disk is unread.
func diskReadings(path string) Readings {
	total, used, free, ok := disk(path)
	if !ok {
		return Readings{}
	}
	var shares []any
	data, _ := os.ReadFile("/proc/self/mounts")
	for _, line := range strings.Split(string(data), "\n") {
		if fields := strings.Split(line, " "); len(fields) > 2 && fields[2] == "virtiofs" {
			if _, _, left, ok := disk(MountPath(fields[1])); ok {
				shares = append(shares, left)
			}
		}
	}
	return Readings{"disk_total_mb": total, "disk_used_mb": used, "disk_free_mb": free, "virtiofs_free_mb": shares}
}

// disk is the disk holding path in MiB, as Python's shutil.disk_usage reads it: used counts the
// blocks reserved for root, free leaves them out.
func disk(path string) (total, used, free float64, ok bool) {
	var fs unix.Statfs_t
	if unix.Statfs(path, &fs) != nil {
		return 0, 0, 0, false
	}
	mib := float64(fs.Frsize) / (1 << 20)
	return float64(fs.Blocks) * mib, float64(fs.Blocks-fs.Bfree) * mib, float64(fs.Bavail) * mib, true
}

// MountPath is a path as the kernel lists it among mounts, its `\NNN` escapes read back: a row
// parts its fields with a space, so each space, tab, newline or backslash in a path is escaped.
func MountPath(path string) string {
	var out strings.Builder
	for i := 0; i < len(path); i++ {
		if path[i] == '\\' && i+3 < len(path) {
			if value, err := strconv.ParseUint(path[i+1:i+4], 8, 8); err == nil {
				out.WriteByte(byte(value))
				i += 3
				continue
			}
		}
		out.WriteByte(path[i])
	}
	return out.String()
}
