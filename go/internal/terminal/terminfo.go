package terminal

import (
	"encoding/binary"
	"fmt"
	"os"
	"path/filepath"
)

// Read the numeric color capability directly: shelling out to tput would make
// help depend on another program. Both compiled terminfo formats use this header.
func terminalColors(term string) int {
	if filepath.Base(term) != term || term == "" {
		return 0
	}
	defaults := []string{"/etc/terminfo", "/lib/terminfo", "/usr/share/terminfo", "/usr/lib/terminfo", "/usr/share/lib/terminfo", "/usr/local/share/terminfo", "/opt/homebrew/share/terminfo"}
	dirs := []string{os.Getenv("TERMINFO")}
	if home, err := os.UserHomeDir(); err == nil {
		dirs = append(dirs, filepath.Join(home, ".terminfo"))
	}
	if paths, set := os.LookupEnv("TERMINFO_DIRS"); set {
		for _, path := range filepath.SplitList(paths) {
			if path == "" {
				dirs = append(dirs, defaults...)
			} else {
				dirs = append(dirs, path)
			}
		}
	} else {
		dirs = append(dirs, defaults...)
	}
	for _, dir := range dirs {
		if dir == "" {
			continue
		}
		for _, prefix := range []string{term[:1], fmt.Sprintf("%x", term[0])} {
			data, err := os.ReadFile(filepath.Join(dir, prefix, term))
			if err != nil || len(data) < 12 {
				continue
			}
			var order binary.ByteOrder = binary.LittleEndian
			magic := order.Uint16(data)
			if magic != 0x011a && magic != 0x021e {
				order = binary.BigEndian
				magic = order.Uint16(data)
			}
			if (magic != 0x011a && magic != 0x021e) || order.Uint16(data[6:]) <= 13 {
				return 0
			}
			size := 2
			if magic == 0x021e {
				size = 4
			}
			offset := 12 + int(order.Uint16(data[2:])) + int(order.Uint16(data[4:]))
			offset += offset % 2 // numeric capabilities start on an even byte
			offset += 13 * size  // max_colors is numeric capability 13
			if offset+size > len(data) {
				return 0
			}
			if size == 4 {
				return int(int32(order.Uint32(data[offset:])))
			}
			return int(int16(order.Uint16(data[offset:])))
		}
	}
	return 0
}
