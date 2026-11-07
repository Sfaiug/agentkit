package box

import (
	"encoding/json"
	"os"
	"path/filepath"
)

// Report is the file in a turn's out directory where the box's first process says how the
// command ended, Python's box.PROCESSES.
const Report = "box-processes.json"

// Exit is how the command boxed in out ended, as its report says, Python's box.returncode: a
// signal's negated, 0 where no report says.
func Exit(out string) int {
	var written struct{ Returncode *int }
	if data, err := os.ReadFile(filepath.Join(out, Report)); err == nil && json.Unmarshal(data, &written) == nil && written.Returncode != nil {
		return *written.Returncode
	}
	return 0
}
