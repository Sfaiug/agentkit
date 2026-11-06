package loop

import (
	"agentkit/internal/handin"
	"agentkit/internal/run"
)

// failsAsProven is whether an earlier finding's replay blocks, Python's replay_findings: it fails
// with the exit code the finding was proven with.  A proof's own `timeout` on a loaded host ends one
// that exited 1 with 124, which shows no defect, while a hang proven with 124 blocks as it hangs.
func failsAsProven(row, now *run.Object) bool {
	code, _ := now.Int("returncode")
	return handin.ProofFailed(now) && code == provenCode(row)
}

// provenCode is the exit code the finding's proof failed with when it was weighed.
func provenCode(row *run.Object) int {
	code, _ := row.Dict("evidence").Int("returncode")
	return code
}
