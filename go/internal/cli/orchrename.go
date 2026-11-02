package cli

import (
	"io"
	"os"
	"slices"
	"time"

	"agentkit/internal/seat"
)

func init() { commands["orch rename"] = orchRename }

// orchRename renames the seat it is given, or with one name the seat this runs in.
func orchRename(args []string, out, errOut io.Writer) int {
	names := without(args, "--auto")
	old := os.Getenv("AGENTKIT_SESSION")
	if len(names) == 2 {
		old = names[0]
	}
	said, known, err := seat.Rename(old, names[len(names)-1], slices.Contains(args, "--auto"), time.Now())
	return orchAnswer("orch rename", said, known, err, out, errOut)
}
