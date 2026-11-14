package notify

import (
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

// codexAcme is a home whose seat acme is a Codex seat on its launch's thread, and what writes a
// file there and the owner messages that thread's rollout holds, each sent at the second named.
func codexAcme(t *testing.T) (state string, write func(path, text string), said func(texts ...[2]string)) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	write = func(path, text string) {
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
	return state, write, func(texts ...[2]string) {
		lines := []string{`{"type": "session_meta", "payload": {"id": "thread-acme", "cwd": "` + cwd + `"}}`}
		for _, each := range texts {
			lines = append(lines, `{"type": "event_msg", "timestamp": "2026-11-05T10:00:`+each[0]+`Z", "payload": `+
				`{"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "`+each[1]+`"}]}}}`)
		}
		write(rollout, strings.Join(lines, "\n")+"\n")
	}
}

// A Codex seat's owner messages are its rollout's, Go's to read until one replies on a question
// card: only the questions that reply names take it as answered (notify.answer_written), which no
// reader of Go's tells, so the seat's answers are left to Python.
func TestACodexReplyOnACardLeavesTheOwnersMessagesToPython(t *testing.T) {
	_, _, said := codexAcme(t)
	asked := [2]string{"01", "Build the acme page."}
	said(asked)
	if said, err := OwnerSaid("acme"); err != nil || !slices.Equal(said, []float64{1793872801}) {
		t.Fatalf("%v, %v", said, err)
	}
	said(asked, [2]string{"02", `<send_user_message_question_reply>[]</send_user_message_question_reply>`})
	if said, err := OwnerSaid("acme"); !errors.Is(err, ErrUnread) {
		t.Fatalf("a reply on a card: %v, %v", said, err)
	}
}

// A typing receipt sent before Codex named its thread keeps the launch it went into: read strictly,
// that launch's receipt there and unreadable is an error, as Python's `went_into` raises; read
// loosely, the line goes into no conversation.  A receipt of a harness no conversation is of reads
// none of its evidence.
func TestAnUnreadableCodexLaunchATypingReceiptNamesCountsStrictly(t *testing.T) {
	state, write, said := codexAcme(t)
	said([2]string{"01", "Build the acme page."})
	typed := func(kind string) string {
		return `{"harness": "` + kind + `", "conversation": null, "launch": {"codex_launch": "` + strings.Repeat("b", 32) +
			`"}, "text": "An earlier automatic prompt.", "source": "ak", "after": 0, "at": 1793872700}` + "\n"
	}
	write(filepath.Join(state, "codex-launch-"+strings.Repeat("b", 32)+".json"), "{\n")
	write(filepath.Join(state, "input-acme.jsonl"), typed("claude"))
	if _, err := Conversations("acme", true); err != nil {
		t.Fatalf("a receipt of another harness: %v", err)
	}
	write(filepath.Join(state, "input-acme.jsonl"), typed("codex"))
	if had, err := Conversations("acme", true); err == nil || errors.Is(err, ErrUnread) {
		t.Fatalf("an unreadable launch read strictly: %#v, %v", had, err)
	}
	if said, err := OwnerSaid("acme"); err != nil || !slices.Equal(said, []float64{1793872801}) {
		t.Fatalf("an unreadable launch read loosely: %v, %v", said, err)
	}
}
