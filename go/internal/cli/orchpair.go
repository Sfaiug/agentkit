package cli

import (
	"fmt"
	"io"
	"strings"

	"agentkit/internal/harness"
)

func init() { commands["orch pair"] = orchPair }

// orchPair prints the code that pairs the provider's app with a seat, and pages nobody.  A word
// Python's Path names otherwise is no seat but the seat's home as given (`pairing_home`): its
// connection.json is opened as Path joins it, never cleaned of a `..` that the filesystem
// resolves through a link to another home.
func orchPair(args []string, out, errOut io.Writer) int {
	seat, connection := args[0], ""
	if _, name := pythonPath(seat); name != seat {
		// a root keeps its own slash, as Path's join does
		connection, _ = pythonPath(strings.TrimSuffix(seat, "/") + "/connection.json")
		seat = ""
	}
	code, known, err := harness.CodexPairing(seat, connection)
	switch {
	case !known:
		return notImplemented(errOut, "orch pair")
	case err != nil:
		fmt.Fprintln(errOut, err)
		return 1
	}
	fmt.Fprintln(out, "Pairing code: "+code)
	return 0
}
