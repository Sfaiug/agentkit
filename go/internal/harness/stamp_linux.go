package harness

import (
	"os"
	"strconv"
	"syscall"

	"agentkit/internal/run"
)

// fileStamp is what Python's stat says changed in a file: [st_dev, st_ino, st_size, st_mtime_ns,
// st_ctime_ns].
func fileStamp(info os.FileInfo) ([]any, bool) {
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return nil, false
	}
	return []any{run.Number(strconv.FormatUint(uint64(stat.Dev), 10)), run.Number(strconv.FormatUint(stat.Ino, 10)),
		run.Number(strconv.FormatInt(stat.Size, 10)), run.Number(strconv.FormatInt(stat.Mtim.Nano(), 10)),
		run.Number(strconv.FormatInt(stat.Ctim.Nano(), 10))}, true
}
