package cli

import (
	"io"
	"os"
	"time"

	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

func init() { commands["orch project"] = orchProject }

// orchProject files the seat it is given, or with one argument the seat this runs in, under a
// checkout.
func orchProject(args []string, out, errOut io.Writer) int {
	name := os.Getenv("AGENTKIT_SESSION")
	if len(args) == 2 {
		name = args[0]
	}
	said, known, err := seat.File(name, args[len(args)-1], terminal.For(out).Width(), time.Now())
	return orchAnswer("orch project", said, known, err, out, errOut)
}
