package tick

import (
	"testing"

	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// A title is kept only where neither follow_title nor sync_title has anything to do: sync_title
// names the seat again over a title it superseded.
func TestATitleIsKeptOnlyWhereNothingRenamesTheSeat(t *testing.T) {
	record := func(fields string) *run.Object {
		value, err := run.DecodeLimited([]byte(fields))
		if err != nil {
			t.Fatal(err)
		}
		return value.(*run.Object)
	}
	for _, each := range []struct {
		record string
		title  any
		kept   bool
	}{
		{`{"session_title": "acme"}`, "", true},
		{`{"session_title": "acme"}`, nil, true},
		{`{"session_title": "acme"}`, "acme", true},
		{`{"session_title": "acme"}`, "billing", false},
		{`{"session_title": "acme", "title_superseded": ["acme-old"]}`, "acme-old", false},
		{`{"session_title": "acme", "title_sync": {"name": "acme", "tries": 1}}`, "acme", false},
		{`{"session_title": "old"}`, "acme", false},
	} {
		if got := titleKept(seat.Live{Name: "acme", Title: each.title, Record: record(each.record)}); got != each.kept {
			t.Errorf("%s titled %v kept: %v", each.record, each.title, got)
		}
	}
}
