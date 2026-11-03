package host

import (
	"os"
	"strings"

	"agentkit/internal/config"
)

// BootID is this boot's, "" where the machine says none.
func BootID() string {
	data, err := os.ReadFile("/proc/sys/kernel/random/boot_id")
	if err != nil {
		return ""
	}
	return strings.TrimFunc(string(data), config.Space)
}
