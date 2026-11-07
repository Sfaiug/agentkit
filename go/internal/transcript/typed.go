package transcript

import "agentkit/internal/harness"

// Typed is what the user side typed in the conversation that seat's record owns, oldest first, and
// that conversation as a typing receipt names it (Python's plugin `conversation` and
// `user_messages`): read by its harness's own reader where it has one, else by its manifest's
// `[transcript]` table from the file its record names, the error where that is there and cannot be
// read (Prompts).  False where Go reads neither.  A named conversation, one the seat left, is the
// one the record names too (harness.Typed).
func Typed(name string, record map[string]any, named string) (conversation any, typed []Prompt, known bool, err error) {
	if owned, typed, known := harness.Typed(name, record, named); known {
		if owned == "" {
			return nil, typed, true, nil
		}
		return owned, typed, true, nil
	}
	names, known := harness.ReadBy(name, record)
	typed, err = Prompts(name, names...)
	return record["conversation"], typed, known, err
}
