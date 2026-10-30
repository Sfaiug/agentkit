package cli

import (
	"errors"
	"fmt"
	"io"

	"agentkit/internal/config"
	"agentkit/internal/update"
)

func init() { commands["update"] = upgrade }

// upgrade is `ak update` where Go carries it out (update.Main); one that would move a harness or
// ~/agentkit is Python's, before Go has written anything.
func upgrade(args []string, out, errOut io.Writer) int {
	code, err := update.Main(config.Repo(), len(args) > 0, out, errOut)
	if errors.Is(err, update.ErrPython) {
		return notImplemented(errOut, "update")
	}
	if err != nil {
		fmt.Fprintf(errOut, "ak update: %v\n", err)
		return 2
	}
	return code
}
