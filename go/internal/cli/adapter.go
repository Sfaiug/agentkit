package cli

import (
	"fmt"
	"io"

	"agentkit/internal/config"
	"agentkit/internal/hooks"
)

// adapter carries out what an adapter stub under go/adapters hands over: `ak adapter <root>
// <harness> <verb>`, root being the checkout the stub sits in.  It never exits 3, which an
// adapter's `interactive` answers to mean it cannot pin the session.
func adapter(args []string, out, errOut io.Writer) int {
	if len(args) != 3 {
		fmt.Fprintln(errOut, "usage: ak adapter <root> <harness> <verb>")
		return 2
	}
	root, harness, verb := args[0], args[1], args[2]
	if verb != "hooks" {
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
