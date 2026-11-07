package handback

import (
	"cmp"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Unclaimed is whether a merge of the run would leave StartFollowups a follow-up it does not
// start, its list not handed on yet: one with no command of its own, which Python's
// start_followups starts as an ordinary run with a regression test.
func Unclaimed(record *run.Object) bool {
	return !record.Has("followup_runs") && slices.ContainsFunc(record.List("followups"), func(item any) bool {
		return followupCheck(record, run.Text(item)) == ""
	})
}

// followupCheck is the failing command the review gave a follow-up, "" for none.
func followupCheck(record *run.Object, item string) string {
	return strings.TrimFunc(cmp.Or(record.Dict("followup_checks"), run.NewObject()).Str(item), config.Space)
}
