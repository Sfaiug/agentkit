package notify

import (
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

// A Codex seat's owner messages are its rollout's, Go's to read until one replies on a question
// card: only the questions that reply names take it as answered (notify.answer_written), which no
// reader of Go's tells, so the seat's answers are left to Python.
func TestACodexReplyOnACardLeavesTheOwnersMessagesToPython(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	write := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil || os.WriteFile(path, []byte(text), 0o600) != nil {
			t.Fatal(path)
		}
	}
	state, token := filepath.Join(home, ".agentkit", "state"), strings.Repeat("a", 32)
	// absolute wherever Go runs, as a receipt's paths are
	rollout, cwd := filepath.Join(home, "rollout.jsonl"), filepath.ToSlash(filepath.Join(home, "acme"))
	write(filepath.Join(state, "session-acme.json"), `{"orchestrator": "astra", "cwd": "`+cwd+`", "codex_launch": "`+token+`"}`)
	write(filepath.Join(state, "codex-launch-"+token+".json"), `{"launch": "`+token+`", "cwd": "`+cwd+`", "event": {
		"session_id": "thread-acme", "transcript_path": "`+filepath.ToSlash(rollout)+`", "hook_event_name": "SessionStart",
		"source": "startup", "cwd": "`+cwd+`"}}`)
	message := func(at, text string) string {
		return `{"type": "event_msg", "timestamp": "2026-11-05T10:00:` + at + `Z", "payload": {"type": "item_completed", ` +
			`"item": {"type": "UserMessage", "content": [{"type": "text", "text": "` + text + `"}]}}}`
	}
	lines := []string{`{"type": "session_meta", "payload": {"id": "thread-acme", "cwd": "` + cwd + `"}}`, message("01", "Build the acme page.")}
	write(rollout, strings.Join(lines, "\n")+"\n")
	if said, err := OwnerSaid("acme"); err != nil || !slices.Equal(said, []float64{1793872801}) {
		t.Fatalf("%v, %v", said, err)
	}
	lines = append(lines, message("02", `<send_user_message_question_reply>[]</send_user_message_question_reply>`))
	write(rollout, strings.Join(lines, "\n")+"\n")
	if said, err := OwnerSaid("acme"); !errors.Is(err, ErrUnread) {
		t.Fatalf("a reply on a card: %v, %v", said, err)
	}
}
