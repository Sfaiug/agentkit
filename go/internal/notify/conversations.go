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
// one it left, as its record keeps them (`left`), then its current one once its harness names it
// (harness.Named), the owner's messages in each without the lines ak typed (withoutAk); none with
// no record.  ErrUnread where Go does not read one, and strictly, with none of them read, where Go
// does not read the owner's words in one as strictly as Python's done check does (harness.Reads);
// read strictly as Python's done check reads, the error where the seat's typing receipts, a
// conversation or the evidence proving it is there and cannot be read.
func Conversations(name string, strictly bool) ([]Conversation, error) {
	current, had, err := Listed(name, strictly)
	if err == nil {
		err = Read(current, had, true)
	}
	if err != nil {
		return nil, err
	}
	return had, nil
}

// Listed is the name that seat goes by now and its conversations as Conversations gives them, none
// of them read yet (Read): no owner's message in any, and the current one's Name "" until read,
// so one listed last with a name is one the seat left.  ErrUnread where Conversations is.
func Listed(name string, strictly bool) (string, []Conversation, error) {
	current, record, err := config.ResolveSession(name)
	if err != nil {
		return "", nil, ErrUnread
	}
	if len(record) == 0 { // an empty one too, which Python's `not record` reads as none
		return current, nil, nil
	}
	left, listed := record["left"].([]any)
	if !listed && record["left"] != nil {
		return "", nil, ErrUnread
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
			return "", nil, ErrUnread // a record no /clear of Python's wrote
		}
		was := maps.Clone(then)
		maps.Copy(was, entry)
		had = append(had, Conversation{Harness: kind, Name: named, Record: was})
	}
	// asked before any is read or judged, so nothing of a harness that has named none yet is; a
	// failure on the way keeps the conversation, for the read or check that follows to report or
	// hand over
	kind := config.SeatHarness(current)
	if named, err := harness.Named(kind, record); err != nil || named != "" {
		had = append(had, Conversation{Harness: kind, Record: record})
	}
	// before any is read, as reading one may keep what its harness's evidence follows
	for _, each := range had {
		if strictly && !harness.Reads(each.Harness, true) {
			return "", nil, ErrUnread
		}
	}
	return current, had, nil
}

// Read gives each conversation Listed gave for the seat that goes by current its name and the
// owner's messages in it, as Conversations reads them: the error Conversations gives.
func Read(current string, had []Conversation, strictly bool) error {
	whole := make([]bool, len(had)) // each read to its end, where no error stopped it
	for i := range had {
		owned, typed, known, err := transcript.Typed(had[i].Harness, had[i].Record, had[i].Name)
		if !known {
			return ErrUnread
		}
		if strictly && err != nil {
			return err
		}
		had[i].Name, _ = owned.(string)
		had[i].Messages, whole[i] = typed, err == nil
	}
	return withoutAk(current, had, whole, strictly)
}
