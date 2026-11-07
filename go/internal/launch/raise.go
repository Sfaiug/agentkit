package launch

import (
	"fmt"
	"path/filepath"
	"time"

	"agentkit/internal/run"
)

// raise is the order of `ak run resume <id> --rounds asked` (asked 0 for none) on the FAIL at its
// round budget that record is, Python's resume_run: its budget at asked, with the review and the
// delivery note its last attempt left gone; or why it is refused: its change has no round left, or
// asked does not raise its budget within what the change has.  Any other run is Python's
// (ErrPython).
func raise(dir string, record *run.Object, asked int) (func(*run.Object), string, error) {
	if !run.AtBudget(record) {
		return nil, "", ErrPython
	}
	id := filepath.Base(dir)
	rounds, _ := record.Int("rounds")
	policy, err := run.PolicyRounds(record)
	if err != nil {
		return nil, "", err
	}
	now := time.Now()
	left, why, err := run.ChangeLeft(record, dir, policy, rounds, now)
	switch {
	case err != nil:
		return nil, "", err
	case why != "":
		return nil, fmt.Sprintf("%s FAILed at its round budget (%d); %s", id, rounds, why), nil
	case asked <= rounds:
		return nil, fmt.Sprintf("%s FAILed at its round budget (%d); give --rounds N above it, at most %d, to continue", id, rounds, rounds+left), nil
	}
	if most, _, err := run.ChangeLeft(record, dir, policy, 0, now); err != nil {
		return nil, "", err
	} else if asked > most {
		return nil, fmt.Sprintf("--rounds %d is over this change's budget: %d of %d rounds across its runs; split or redesign the task", asked, most, policy), nil
	}
	return func(record *run.Object) {
		record.Set("rounds", asked)
		record.Delete("review_pending")
		run.SetAll(record, "merge_failed", false, "merge_note", nil)
	}, "", nil
}
