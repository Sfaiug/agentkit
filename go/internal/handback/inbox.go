package handback

import (
	"io"

	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// AskAgain asks the merge question the run still owes the inbox, as Python's offer_endings does:
// one the seat never took is typed again before the owner hears it, and one it took whose ping
// failed is only pinged, as is one kept before `asked` was.  The marks go on the record as it
// stands.  False where Go does not ask it, nothing typed or written.
func AskAgain(dir string, record *run.Object, say func(string), errOut io.Writer) bool {
	question := record.Dict("pending_inbox")
	if question == nil {
		return false
	}
	asked := !question.Has("asked") || question.Truthy("asked")
	sent, carried := seat.AskInbox(question.Str("question"), question.Str("url"), question.Str("sha"), asked, func() {
		taken := question.Copy()
		taken.Set("asked", true)
		mark(dir, record, "pending_inbox", taken)
	}, say, errOut)
	if sent {
		mark(dir, record, "pending_inbox", nil)
	}
	return carried
}
