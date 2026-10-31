package cli

import (
	"fmt"
	"io"

	"agentkit/internal/adapters"
	"agentkit/internal/config"
	"agentkit/internal/hooks"
)

// adapter carries out what an adapter stub under go/adapters hands over: `ak adapter <root>
// <harness> <verb> [<arg>...]`, root being the checkout the stub sits in.  It never exits 3,
// which an adapter's `interactive` answers to mean it cannot pin the session.
func adapter(args []string, out, errOut io.Writer) int {
	if len(args) < 3 {
		fmt.Fprintln(errOut, "usage: ak adapter <root> <harness> <verb> [<arg>...]")
		return 2
	}
	root, harness, verb, rest := args[0], args[1], args[2], args[3:]
	switch verb {
	case "interactive":
		return adapters.Interactive(root, harness, rest, out, errOut)
	case "seat":
		return adapters.Seat(harness, rest, errOut)
	case "run":
		return adapters.Turn(harness, rest, errOut)
	case "hooks":
	default:
		fmt.Fprintf(errOut, "ak adapter: %s %s is not carried out in Go yet\n", harness, verb)
		return 2
	}
	table, ok, err := config.Hooks(harness)
	if err != nil {
		fmt.Fprintf(errOut, "ak adapter: %s\n", err)
		return 2
	}
	if !ok {
		fmt.Fprintf(errOut, "ak adapter: %s has no [hooks.install] table\n", harness)
		return 2
	}
	return hooks.Install(table, root, out, errOut)
}
