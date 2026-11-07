package box

import (
	"encoding/json"
	"os"
	"path/filepath"
)

// CPU is the CPU seconds the processes of the command boxed in out spent, as its report says,
// Python's box.cpu_seconds: nil where no report says.
func CPU(out string) *float64 {
	var written struct {
		CPUSeconds *float64 `json:"cpu_seconds"`
	}
	data, err := os.ReadFile(filepath.Join(out, Report))
	if err != nil || json.Unmarshal(data, &written) != nil {
		return nil
	}
	return written.CPUSeconds
}
