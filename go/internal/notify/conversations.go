package notify

import (
	"maps"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/transcript"
)

// A Conversation is one a seat had, as its owner's words are read from it: the harness that
// keeps it, the seat's record naming it, its name ("" where the record names none), and the
// owner's messages in it.
type Conversation struct {
	Harness, Name string
	Record        map[string]any
	Messages      []transcript.Prompt
}

// Conversations is each conversation that seat had, oldest first (notify.conversations_of): each
// one it left, as its record keeps them (`left`), then its current one, the owner's messages in
// each as OwnerMessages reads them; none with no record.  ErrUnread where Go does not read one,
// and strictly, with none of them read, where Go does not read the owner's words in one as
// strictly as Python's done check does (harness.Reads); the error where the seat's typing
// receipts cannot be read.
func Conversations(name string, strictly bool) ([]Conversation, error) {
	current, record, err := config.ResolveSession(name)
	if err != nil {
		return nil, ErrUnread
	}
	if len(record) == 0 { // an empty one too, which Python's `not record` reads as none
		return nil, nil
	}
	left, listed := record["left"].([]any)
	if !listed && record["left"] != nil {
		return nil, ErrUnread
	}
	// each read under the record as it was then: none of the current launch's evidence, which
	// names the conversation it is on now
	then := maps.Clone(record)
	for _, key := range harness.LaunchKeys {
		delete(then, key)
	}
	var had []Conversation
	for _, each := range left {
		entry, _ := each.(map[string]any)
		kind, _ := entry["harness"].(string)
		named, _ := entry["conversation"].(string)
		if kind == "" || named == "" {
			return nil, ErrUnread // a record no /clear of Python's wrote
		}
		was := maps.Clone(then)
		maps.Copy(was, entry)
		had = append(had, Conversation{Harness: kind, Name: named, Record: was})
	}
	had = append(had, Conversation{Harness: config.SeatHarness(current), Record: record})
	// before any is read, as reading one may keep what its harness's evidence follows
	for _, each := range had {
		if strictly && !harness.Reads(each.Harness, true) {
			return nil, ErrUnread
		}
	}
	for i := range had {
		if had[i].Name, had[i].Messages, err = ownerIn(current, had[i].Harness, had[i].Record, had[i].Name); err != nil {
			return nil, err
		}
	}
	return had, nil
}
