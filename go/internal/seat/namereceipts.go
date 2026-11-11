package seat

import (
	"strings"

	"agentkit/internal/harness"
	"agentkit/internal/run"
	script "agentkit/internal/transcript"
)

// nameReceipts writes into each of the seat's typing receipts the conversation its launch's own
// evidence names now (orch.name_receipts, harness.WentInto), as a launch is about to retire that
// evidence: a receipt naming none would then no longer tell ak's line from the owner's.  Under
// the seat's typing lock, the one every receipt is written under.
func nameReceipts(name string) error {
	path := ownFile("input", name)
	var kept, named strings.Builder
	for sent := range script.Entries(path) {
		kept.WriteString(run.Line(sent) + "\n")
		conversation := any(nil)
		if into := harness.WentInto(sent.Str("harness"), sent); into != "" {
			conversation = into
		}
		sent.Set("conversation", conversation)
		named.WriteString(run.Line(sent) + "\n")
	}
	if named.String() == kept.String() {
		return nil
	}
	return replace(path, []byte(named.String()))
}
