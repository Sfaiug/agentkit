package harness

import (
	"math/big"
	"unicode/utf16"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// promptEvent is the harness's manifest's `UserPromptSubmit` event, nil for none.
func promptEvent(name string) map[string]any {
	entries, _ := config.HookEvents(name)
	for _, entry := range entries {
		if entry["name"] == "UserPromptSubmit" {
			return entry
		}
	}
	return nil
}

// TakesContext is whether what its prompt hook prints as context reaches the model with that
// prompt (`prompt_context`).
func TakesContext(name string) bool {
	return promptEvent(name)["context"] == true
}

// ContextFits is whether text reaches the model whole from its prompt hook: no longer than
// `context_limit`, counted in UTF-16 code units as Claude Code counts it; any length where its
// manifest declares none.
func ContextFits(name, text string) bool {
	limit, declared := promptEvent(name)["context_limit"].(*big.Int)
	return !declared || big.NewInt(int64(len(utf16.Encode([]rune(text))))).Cmp(limit) <= 0
}

// Owns is whether that conversation is the seat's own, on evidence its harness vouches for
// (orch.owns); false for known where Go does not read that harness's evidence yet.
func Owns(name string, record *run.Object, conversation string) (owned, known bool) {
	hook := plugins[name].owns
	if hook == nil {
		return false, false
	}
	return conversation != "" && hook(record, conversation), true
}
