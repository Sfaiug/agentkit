package harness

import (
	"os"

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
	if plugged && !own.opens && (own.launch == nil || record["conversation"] == nil || record["conversation"] == "") {
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

// Opened is whether that harness has written the conversation a seat's record names down yet, as
// its plugin's `opened` answers: a store nothing knows is taken at its word, as is a conversation
// its harness reported; false where its plugin knows one Go does not read.
func Opened(name string, record map[string]any) (opened, known bool) {
	own, plugged := plugins[name]
	if own.conversation == nil {
		known = !plugged || own.launch != nil || own.owned != nil
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
