package seat

import (
	"os"
	"syscall"
	"time"
)

func terminalQuiet(info os.FileInfo) bool {
	stat, ok := info.Sys().(*syscall.Stat_t)
	return ok && time.Since(time.Unix(stat.Atimespec.Sec, stat.Atimespec.Nsec)) >= 120*time.Second
}
