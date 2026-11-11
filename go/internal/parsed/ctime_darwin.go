package parsed

import (
	"os"
	"syscall"
	"time"
)

// changed is when the file's inode last changed, its ctime.
func changed(info os.FileInfo) time.Time {
	if stat, ok := info.Sys().(*syscall.Stat_t); ok {
		return time.Unix(stat.Ctimespec.Unix())
	}
	return time.Time{}
}
