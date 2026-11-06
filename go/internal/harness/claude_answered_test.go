package harness

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// A card's answer is the owner's words beside the seat's question and choices; a subagent's card
// answers nothing, and a conversation that cannot be read is an error, never an empty one.
func TestClaudeAnsweredReadsTheOwnersCards(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	record := map[string]any{"conversation": "c-1", "cwd": "/home/acme/code/fix-api"}
	path := claudeConversation(record)
	question := `{"questions": [{"question": "Which layout?", "options": [{"label": "Tabbed", "description": "One tab each."}]}], ` +
		`"answers": {"Which layout?": "(notes only)"}, "annotations": {"Which layout?": {"notes": "Add a search box."}}}`
	lines := []string{
		`{"type": "user", "timestamp": "2026-11-05T10:00:00Z", "message": {"role": "user", "content": "Pick a layout."}}`,
		`{"type": "assistant", "message": {"content": [{"type": "text", "text": "Here are two."}, {"type": "tool_use", "id": "toolu_1", "name": "AskUserQuestion"}]}}`,
		`not a line of JSON`,
		`{"type": "user", "timestamp": "2026-11-05T10:01:00Z", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_1"}]}, "toolUseResult": ` + question + `}`,
		`{"type": "user", "isSidechain": true, "timestamp": "2026-11-05T10:02:00Z", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_1"}]}, "toolUseResult": ` + question + `}`,
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0o666); err != nil {
		t.Fatal(err)
	}
	said, cards, err := claudeAnswered(record)
	if want := []Turn{{"user", "Pick a layout."}, {"model", "Here are two."}}; err != nil || !reflect.DeepEqual(said, want) {
		t.Fatalf("said %v, %v; want %v", said, err, want)
	}
	want := []Card{{At: 1793872860, Question: "Which layout?", Answer: "Add a search box.", Choices: []Choice{{"Tabbed", "One tab each."}}}}
	if !reflect.DeepEqual(cards, want) {
		t.Fatalf("cards %+v; want %+v", cards, want)
	}
	if err := os.Remove(path); err != nil || os.Mkdir(path, 0o777) != nil {
		t.Fatal("cannot make the conversation a folder")
	}
	if _, _, err := claudeAnswered(record); err == nil {
		t.Fatal("a conversation that cannot be read read as one")
	}
}
