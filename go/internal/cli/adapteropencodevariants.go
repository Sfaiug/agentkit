package cli

import (
	"fmt"
	"io"
	"os"

	"agentkit/internal/harness"
)

// `variants <model>`, as adapters/opencode.sh answers it: the document defining the variants a
// launch on that model defines itself, for a move to it to restart.  A named account is refused
// first, as that script refuses one for every verb.
func init() {
	ownVerbs["opencode variants"] = func(args []string, out, errOut io.Writer) int {
		if account := os.Getenv("AGENTKIT_ACCOUNT"); account != "" {
			fmt.Fprintf(errOut, "opencode: account %s refused; OpenCode keeps logins and sessions in one opencode.db, so a login of its own cannot resume a conversation\n", account)
			return 1
		}
		if len(args) < 1 {
			fmt.Fprintln(errOut, "opencode.sh variants needs <model>")
			return 2
		}
		fmt.Fprintln(out, harness.OpencodeVariants(args[0]))
		return 0
	}
}
