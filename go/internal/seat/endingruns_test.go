package seat

import (
	"testing"

	"agentkit/internal/run"
)

func TestACompletedDeliveryBetweenTickRowsDoesNotHideTheSeat(t *testing.T) {
	for _, scenario := range []string{"decision", "merged", "not needed", "typed merge", "pending interruption"} {
		t.Run(scenario, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			write(t, stateFile(home, "plan-acme.md"), "- [x] API ships\n")
			ending := run.Fields("state", "fail", "finished_at", seconds(moment), "handback_pending", true)
			switch scenario {
			case "merged", "typed merge":
				run.SetAll(ending, "state", "pass", "merged", true)
				if scenario == "typed merge" {
					ending.Set("handback_typed", run.Fields("pane", "%1"))
				}
			case "not needed":
				ending.Set("state", "not_needed")
			case "pending interruption":
				ending.Set("state", "interrupted")
			}
			if _, known := viewRun(ending, moment); !known {
				t.Fatal("seat stopped reading the run before the endings row")
			}
			news, err := telling(climbing{name: "acme", now: seconds(moment), file: run.NewObject(),
				found: sight{state: "at_prompt", authority: "screen"}, mine: []ran{{name: "fix-api", record: ending}}})
			wantNews := scenario == "decision" || scenario == "typed merge"
			if err != nil || (news != nil) != wantNews {
				t.Fatalf("news %v, error %v", news, err)
			}
		})
	}
}
