package notify

import (
	"errors"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/transcript"
)

// OwnerSaid is when the owner wrote each of their messages in that seat's conversation, oldest
// first (notify.owner_said), as OwnerMessages reads them: none where they cannot be read.
func OwnerSaid(name string) ([]float64, error) {
	_, messages, err := OwnerMessages(name)
	if errors.Is(err, ErrUnread) {
		return nil, err
	}
	var said []float64
	for _, message := range messages {
		said = append(said, message.At)
	}
	return said, nil
}

// OwnerMessages is the conversation that seat's record owns and the owner's messages in it,
// oldest first (notify.owner_messages): none with no record or no conversation to read;
// ErrUnread where its harness's are not Go's to read yet, and the error where the seat's typing
// receipts cannot be read (strict).  A line ak typed itself reads as the owner's in the
// conversation, so each of the seat's typing receipts takes out the first message after it in
// its words, once, as `user_messages` does; one the owner relayed stays theirs.
func OwnerMessages(name string) (string, []transcript.Prompt, error) {
	current, record, err := config.ResolveSession(name)
	if err != nil {
		return "", nil, ErrUnread
	}
	if record == nil {
		return "", nil, nil
	}
	return ownerIn(current, config.SeatHarness(current), record)
}

// ownerIn is OwnerMessages of the conversation the seat's record names, as that harness keeps it.
func ownerIn(current, kind string, record map[string]any) (string, []transcript.Prompt, error) {
	owned, messages, known := transcript.Typed(kind, record)
	if !known {
		return "", nil, ErrUnread
	}
	conversation, _ := owned.(string)
	matched, ours := make([]bool, len(messages)), make([]bool, len(messages))
	err := harness.Entries(filepath.Join(config.Home(), "state", config.SeatFileNames(current)["input"]), func(sent *run.Object) {
		after, dated := sent.Num("after")
		if !dated || sent.Str("harness") != kind || sent.Str("conversation") != conversation {
			return
		}
		for index, message := range messages {
			if !matched[index] && float64(index) >= after && message.Text == sent.Str("text") {
				matched[index], ours[index] = true, sent.Str("source") != "owner"
				return
			}
		}
	})
	if err != nil {
		return "", nil, err
	}
	var said []transcript.Prompt
	for index, message := range messages {
		if !ours[index] {
			said = append(said, message)
		}
	}
	return conversation, said, nil
}
