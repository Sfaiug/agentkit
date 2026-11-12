package transcript

import "agentkit/internal/harness"

// Typed is what the user side typed in the conversation that seat's record owns, oldest first, and
// that conversation as a typing receipt names it (Python's plugin `conversation` and
// `user_messages`): read by its harness's own reader where it has one (harness.Typed), else by its
// manifest's `[transcript]` table from the file its record names (Prompts), the error where that
// is there and cannot be read.  False where Go reads neither.  A named conversation, one the seat
// left, is the one the record names too.
func Typed(name string, record map[string]any, named string) (conversation any, typed []Prompt, known bool, err error) {
	if owned, typed, known, err := harness.Typed(name, record, named); known {
		if owned == "" {
			return nil, typed, true, err
		}
		return owned, typed, true, err
	}
	names, known := harness.ReadBy(name, record)
	typed, err = Prompts(name, names...)
	return record["conversation"], typed, known, err
}
