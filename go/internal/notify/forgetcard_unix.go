//go:build unix

package notify

import (
	"io/fs"
	"os"
	"syscall"
)

// single is whether a card is a plain file of this user's under no other name, as
// retention.safe has it: anything else is not the seat's to retire or remove.
func single(info fs.FileInfo) bool {
	stat, ok := info.Sys().(*syscall.Stat_t)
	return ok && info.Mode().IsRegular() && int(stat.Uid) == os.Getuid() && stat.Nlink == 1
}
