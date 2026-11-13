package cli

import (
	"fmt"
	"io"

	"agentkit/internal/harness"
)

// `variants <model>`, as adapters/opencode.sh answers it: the document defining the variants a
// launch on that model defines itself, for a move to it to restart.
func init() {
	ownVerbs["opencode variants"] = func(args []string, out, errOut io.Writer) int {
		if len(args) < 1 {
			fmt.Fprintln(errOut, "opencode.sh variants needs <model>")
			return 2
		}
		fmt.Fprintln(out, harness.OpencodeVariants(args[0]))
		return 0
	}
}
