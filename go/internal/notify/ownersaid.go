package notify

import (
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/transcript"
)

// OwnerSaid is when the owner wrote each of their messages in that seat's conversation, oldest
// first (notify.owner_said): none with no record or no conversation to read; ErrUnread where its
// harness's are not Go's to read yet.  A line ak typed itself reads as the owner's in the
// conversation, so each of the seat's typing receipts takes out the first message after it in
// its words, once, as `user_messages` does; one the owner relayed stays theirs.
func OwnerSaid(name string) ([]float64, error) {
	current, record, err := config.ResolveSession(name)
	if err != nil {
		return nil, ErrUnread
	}
	if record == nil {
		return nil, nil
	}
	kind := config.SeatHarness(current)
	owned, messages, known := transcript.Typed(kind, record)
	if !known {
		return nil, ErrUnread
	}
	conversation, _ := owned.(string)
	matched, ours := make([]bool, len(messages)), make([]bool, len(messages))
	for sent := range transcript.Entries(filepath.Join(config.Home(), "state", config.SeatFileNames(current)["input"])) {
		after, dated := sent.Num("after")
		if !dated || sent.Str("harness") != kind || sent.Str("conversation") != conversation {
			continue
		}
		for index, message := range messages {
			if !matched[index] && float64(index) >= after && message.Text == sent.Str("text") {
				matched[index], ours[index] = true, sent.Str("source") != "owner"
				break
			}
		}
	}
	var said []float64
	for index, message := range messages {
		if !ours[index] {
			said = append(said, message.At)
		}
	}
	return said, nil
}
