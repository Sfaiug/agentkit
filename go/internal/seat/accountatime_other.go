//go:build !linux && !darwin

package seat

import "os"

func terminalQuiet(os.FileInfo) bool { return false }
