package cli

import (
	"io"
	"slices"

	"agentkit/internal/harness"
	"agentkit/internal/plan"
)

// Main carries out one ak command, then writes down each conversation it learned a seat owns and
// each answer it made to whether a seat owes its done check: none where it handed the command over
// (exit 3) or ran it dry, so no reader has to know whether either follows its ask.
func Main(args []string, out, errOut io.Writer) int {
	code := carry(args, out, errOut)
	carried := code != 3 && !slices.Contains(args, "--dry-run")
	harness.Claim(carried)
	plan.KeepAnswers(carried)
	return code
}
