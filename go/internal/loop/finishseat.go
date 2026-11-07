package loop

import (
	"context"
	"fmt"

	"agentkit/internal/handback"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

// FinishSeat is the shared ending of every run that delivered, whichever way it merged.
func FinishSeat(dir string, record *run.Object) *run.Object {
	say := func(line string) { fmt.Fprintln(stampedLog{dir}, line) }
	if session := run.Seat(record); session != "" && (record.Truthy("merged") || record.Str("state") == "not_needed") {
		check := ""
		if origin := record.Dict("followup"); origin != nil {
			check = origin.Str("check")
		}
		if err := plan.Delivered(context.Background(), session, check); err != nil {
			say("WARN could not check the seat's plan: " + err.Error())
		}
	}
	if err := handback.StartFollowups(dir, launchForSeat, say); err != nil {
		say("WARN could not start follow-ups: " + err.Error())
	}
	current, _ := run.Read(dir)
	return current
}
