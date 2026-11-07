package cli

import (
	"io"
	"slices"

	"agentkit/internal/harness"
)

// Main carries out one ak command, then writes down each conversation it learned a seat owns: none
// where it handed the command over (exit 3) or ran it dry, so no reader has to know whether either
// follows its ask.
func Main(args []string, out, errOut io.Writer) int {
	code := carry(args, out, errOut)
	harness.Claim(code != 3 && !slices.Contains(args, "--dry-run"))
	return code
}
