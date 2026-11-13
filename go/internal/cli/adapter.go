package cli

import (
	"fmt"
	"io"

	"agentkit/internal/adapters"
	"agentkit/internal/config"
	"agentkit/internal/handover"
	"agentkit/internal/hooks"
	"agentkit/internal/seat"
)

// ownVerbs holds the adapter verbs Go carries out for one harness alone, by that harness and
// verb (`opencode variants`); each one's file adds itself, as a command joins commands.
var ownVerbs = map[string]func(args []string, out, errOut io.Writer) int{}

// adapter carries out what an adapter stub under go/adapters hands over: `ak adapter <root>
// <harness> <verb> [<arg>...]`, root being the checkout the stub sits in.  It exits 3 for a hook
// whose case it hands over, and where an adapter's `interactive` answers that it cannot pin the
// session, which hands nothing over.  A verb of one harness alone is its own, from ownVerbs.
func adapter(args []string, out, errOut io.Writer) int {
	if len(args) < 3 {
		fmt.Fprintln(errOut, "usage: ak adapter <root> <harness> <verb> [<arg>...]")
		return 2
	}
	root, harness, verb, rest := args[0], args[1], args[2], args[3:]
	handover.Runs("adapter " + harness + " " + verb)
	if own := ownVerbs[harness+" "+verb]; own != nil {
		return own(rest, out, errOut)
	}
	switch verb {
	case "interactive":
		return adapters.Interactive(root, harness, rest, out, errOut)
	case "seat":
		return adapters.Seat(harness, rest, errOut, seat.Follow(harness), seat.LookNow, seat.StartLook)
	case "run":
		return adapters.Turn(harness, rest, errOut)
	case "auth":
		return adapters.Auth(harness, rest, out, errOut)
	case "lend":
		return adapters.Lend(harness, rest, out, errOut)
	case "login":
		return adapters.Login(harness, rest, out, errOut)
	case "forget":
		return adapters.Forget(harness, errOut)
	case "hook":
		return adapterHook(harness, rest, out)
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
