package harness

import (
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Owned is the conversation that harness says a seat's record owns once it has reconciled it
// (its plugin's `conversation` and `reconcile`), "" for none; false where the answer hangs on
// what Go does not do: a store of its own, or a record to reconcile.  A harness with no plugin,
// only an adapter, takes the defaults.
func Owned(name string, record map[string]any) (string, bool) {
	own, plugged := plugins[name]
	if own.owned != nil {
		return own.owned(record), true
	}
	if plugged && !own.opens {
		return "", false
	}
	conversation, isText := record["conversation"].(string)
	if !isText && record["conversation"] != nil {
		return "", false
	}
	vouched := record["id_source"] == "launcher"
	if own.owns != nil {
		data := run.NewObject()
		for key, value := range record {
			data.Set(key, value)
		}
		vouched = own.owns(data, conversation)
	}
	if conversation != "" && !vouched {
		return "", false
	}
	return conversation, true
}

// Recorded is each conversation a seat's record proves (harness.recorded_conversations): the one
// it names, then each by every harness's own evidence, its plugin's `owned`: the one its
// Antigravity launch saw, the one its Muse launch reported; "" for none.
func Recorded(record *run.Object) []string {
	return []string{record.Str("conversation"), antigravityMine(record), museReceived(map[string]any{"muse_launch": record.Get("muse_launch")})}
}

// launchSeats is the seat whose record carries that launch's token under key, "" for none, and
// every other seat's record, as they stand: a rename pointer is no seat's.  Each is read as shown,
// so a lone surrogate Python reads in one leaves the rest of it to count.
func launchSeats(key, token string) (name string, seat *run.Object, others []*run.Object) {
	for _, path := range config.SeatFiles() {
		data, _ := os.ReadFile(path)
		value, _ := run.DecodeShown(data)
		kept, _ := value.(*run.Object)
		if kept == nil || kept.Has(config.Renamed) {
			continue
		}
		if name == "" && kept.Get(key) == token {
			name, seat = strings.TrimSuffix(strings.TrimPrefix(filepath.Base(path), "session-"), ".json"), kept
		} else {
			others = append(others, kept)
		}
	}
	return name, seat, others
}

// namedElsewhere is whether a seat's record but the one carrying that launch's token names the
// conversation, as its own or as one it left (harness.named_elsewhere): never that seat's to learn.
func namedElsewhere(key, token, conversation string) bool {
	_, _, others := launchSeats(key, token)
	return slices.ContainsFunc(others, func(other *run.Object) bool {
		left, _ := other.Get("left").([]any)
		return slices.Contains(Recorded(other), conversation) ||
			slices.ContainsFunc(left, func(was any) bool {
				entry, _ := was.(*run.Object)
				return entry != nil && entry.Get("conversation") == conversation
			})
	})
}

// Learns is whether that harness's own evidence names the conversation a seat is on (Current),
// where its record may name none yet.
func Learns(name string) bool { return plugins[name].owned != nil }

// Current is the conversation a seat's record is on, as its plugin's `conversation` reads it
// (notify.conversation_of): the one its harness reported where it reports its own, else the one
// the record names, vouched for or not; "" for none.
func Current(name string, record map[string]any) string {
	if owned := plugins[name].owned; owned != nil {
		return owned(record)
	}
	conversation, _ := record["conversation"].(string)
	return conversation
}

// WentInto is the conversation a typing receipt's line went into: the one it names, else the one
// its launch's own evidence reported, "" while that names none.  A receipt keeps that evidence
// where the harness had not named the conversation yet, as on a fresh Muse launch.
func WentInto(name string, sent *run.Object) string {
	conversation, _ := WentIntoFound(name, sent)
	return conversation
}

// WentIntoFound is WentInto, and the error where that evidence is there and cannot be read, as
// Python's `went_into` raises reading strictly (harness.unread).
func WentIntoFound(name string, sent *run.Object) (string, error) {
	launch := sent.Dict("launch")
	if conversation := sent.Str("conversation"); conversation != "" || launch == nil {
		return conversation, nil
	}
	var evidence map[string]any // as config.ResolveSession reads a record
	json.Unmarshal([]byte(run.Line(launch)), &evidence)
	own := plugins[name]
	if own.reported != nil {
		return own.reported(evidence), nil
	}
	if own.found != nil {
		return own.found(evidence)
	}
	conversation, _ := Owned(name, evidence)
	return conversation, nil
}

// Opened is whether that harness has written the conversation a seat's record names down yet, as
// its plugin's `opened` answers: a store nothing knows is taken at its word, as is a conversation
// its harness reported; false where its plugin knows one Go does not read.
func Opened(name string, record map[string]any) (opened, known bool) {
	own, plugged := plugins[name]
	if own.opened != nil {
		return own.opened(record), true
	}
	if own.conversation == nil {
		known = !plugged || own.owned != nil
		return known, known
	}
	_, err := os.Stat(own.conversation(record))
	return err == nil, true
}

// FreshWords is what a seat of that harness starting without a past is said to be doing, its
// manifest's `[conversation] fresh_words` where it has them.
func FreshWords(name string) string {
	section, _ := config.Section(name, "conversation")
	if words, _ := section["fresh_words"].(string); words != "" {
		return words
	}
	return "no conversation recorded; it starts fresh"
}
