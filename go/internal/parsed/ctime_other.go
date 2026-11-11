//go:build !linux && !darwin

package parsed

import (
	"os"
	"time"
)

// changed is no time where the system's stat keeps no ctime, as Windows' does not: its mtime alone
// vouches.
func changed(os.FileInfo) time.Time { return time.Time{} }
