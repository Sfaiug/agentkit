package transcript

import "agentkit/internal/harness"

// Typed is what the user side typed in the conversation that seat's record owns, oldest first, and
// that conversation as a typing receipt names it (Python's plugin `conversation` and
// `user_messages`): read by its harness's own reader where it has one, else by its manifest's
// `[transcript]` table from the file its record names.  False where Go reads neither.
func Typed(name string, record map[string]any) (conversation any, typed []Prompt, known bool) {
	if owned, typed, known := harness.Typed(name, record); known {
		if owned == "" {
			return nil, typed, true
		}
		return owned, typed, true
	}
	path, known := harness.Conversation(name, record)
	return record["conversation"], Prompts(name, path), known
}
