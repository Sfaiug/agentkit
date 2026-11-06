package harness

import (
	"os"
	"path/filepath"
	"testing"
)

func TestClaudeHandoverKeepsVisibleConversationInOrder(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	record := map[string]any{"orchestrator": "fable", "cwd": t.TempDir(), "conversation": "conv-acme"}
	if handed, known := Handover("claude", record); !known || handed != "" {
		t.Fatal("a conversation never opened hands over nothing", handed, known)
	}
	path := claudeConversation(record)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	text := `{"type":"user","message":{"role":"user","content":[{"type":"text","text":"please fix it"}]}}
{"type":"assistant","isMeta":true,"message":{"content":[{"type":"text","text":"bookkeeping"}]}}
{"type":"assistant","isApiErrorMessage":true,"message":{"content":[{"type":"text","text":"an error"}]}}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"not the owner"}]}}
{"type":"user","message":{"role":"user","content":"<task-notification>bookkeeping"}}
{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"private"},{"type":"text","text":"fixed it"}]}}
{"type":"attachment","attachment":{"type":"queued_command","origin":{"kind":"human"},"prompt":"one more thing"}}
{"type":"assistant","isSidechain":true,"message":{"content":[{"type":"text","text":"a subagent"}]}}
`
	if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	want := "## Its conversation on fable\n\n**user:** please fix it\n\n**fable:** fixed it\n\n**user:** one more thing\n\n"
	if handed, known := Handover("claude", record); !known || handed != want {
		t.Fatal(handed, known)
	}
	delete(record, "conversation")
	if handed, known := Handover("claude", record); !known || handed != "## Its conversation on fable\n\nIt cannot be read here.\n\n" {
		t.Fatal(handed, known)
	}
}
