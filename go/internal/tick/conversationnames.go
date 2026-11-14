package tick

import (
	"errors"
	"fmt"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// keepConversations is Python's watch.keep_conversations: each conversation of every seat, those it
// left included (notify.Listed), given ak's own name for its file where its harness keeps one
// (harness.Keep), none of them read.  Every seat is listed before any name is given, so a seat Go
// cannot tell Python's pass about hands over with nothing written; one Python's raises on ends the
// row on that error, the seats before it given their names, as Python's are.
func keepConversations() error {
	var had []notify.Conversation
	var raised error
	for _, path := range config.SeatFiles() {
		each, err := seatConversations(path)
		if errors.Is(err, errLeft) {
			return errLeft
		}
		if raised = err; err != nil {
			break
		}
		had = append(had, each...)
	}
	for _, each := range had {
		if err := harness.Keep(each.Harness, each.Record); err != nil {
			return err
		}
	}
	return raised
}

// seatConversations is the conversations of the seat whose record is that file as Python's
// notify.conversations_of finds them: none for a rename's pointer, which config.session_records
// leaves out; what it raises with where it raises; errLeft where Go cannot tell.
func seatConversations(path string) ([]notify.Conversation, error) {
	name, _ := config.SeatFileOwner(filepath.Base(path))
	current, record, err := config.ResolveSession(name)
	if err != nil {
		return nil, errLeft
	}
	// as Python's json reads it, each number an int or a float
	written, err := run.Shared(path)
	if err != nil {
		return nil, errLeft
	}
	if current != name || written == nil {
		return nil, nil
	}
	// Python's asks the harness which conversation the seat is on before it reads `left`
	if _, err := harness.Named(config.SeatHarness(current), record); err != nil {
		return nil, errLeft
	}
	if err := leftRaises(written); err != nil {
		return nil, err
	}
	_, had, err := notify.Listed(name, false)
	if err != nil {
		return nil, errLeft
	}
	return had, nil
}

// leftRaises is what Python's conversations_of raises with on the record's `left`, nil where it
// raises nothing: it must be a list of mappings, each, under the record's own keys but the launch's
// (harness.LaunchKeys), naming a harness and a conversation.  A string or object is iterated, its
// characters or keys no mapping.
func leftRaises(record *run.Object) error {
	var gone []any
	switch left := record.Get("left").(type) {
	case []any:
		gone = left
	case string:
		if left != "" {
			return errors.New("'str' object is not a mapping")
		}
	case *run.Object:
		if len(left.Keys()) > 0 {
			return errors.New("'str' object is not a mapping")
		}
	default:
		if record.Has("left") {
			return fmt.Errorf("'%s' object is not iterable", pyType(left))
		}
	}
	for _, each := range gone {
		if _, ok := each.(*run.Object); !ok {
			return fmt.Errorf("'%s' object is not a mapping", pyType(each))
		}
	}
	for _, each := range gone {
		for _, key := range []string{"harness", "conversation"} {
			if !each.(*run.Object).Has(key) && (!record.Has(key) || slices.Contains(harness.LaunchKeys, key)) {
				return fmt.Errorf("'%s'", key)
			}
		}
	}
	return nil
}

// pyType is the name of the type Python's json reads that value as.
func pyType(value any) string {
	switch value := value.(type) {
	case nil:
		return "NoneType"
	case bool:
		return "bool"
	case run.Number:
		if run.Integral(value) {
			return "int"
		}
		return "float"
	case string:
		return "str"
	case []any:
		return "list"
	}
	return "dict"
}
