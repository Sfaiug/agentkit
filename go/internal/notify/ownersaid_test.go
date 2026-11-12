package notify

import (
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

func TestOwnerSaidIsTheOwnersWordsInTheSeatsConversation(t *testing.T) {
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
	state := filepath.Join(home, ".agentkit", "state")
	line := func(at, text string) string {
		return `{"type": "user", "timestamp": "2026-10-31T05:00:` + at + `Z", "message": {"role": "user", "content": "` + text + `"}}`
	}
	// the seat's folder: its working directory, each character not a letter or digit a hyphen
	chat := filepath.Join(home, ".claude-work", "projects", "-code-acme", "conv-1.jsonl")
	write(filepath.Join(state, "session-acme.json"),
		`{"orchestrator": "opus", "cwd": "/code/acme", "conversation": "conv-1", "account": "work"}`)
	write(chat, strings.Join([]string{
		line("03.000", "the second"),
		line("01.000", "the first"),
		line("02.000", "ak typed this"), // a receipt's, gone
		line("04.000", "the owner relayed this"),
		line("05.000", "ak typed this"), // the receipt took one
		`{"type": "user", "timestamp": "2026-10-31T05:00:06Z", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "Yes"}]}}`,
		`{"type": "user", "isMeta": true, "timestamp": "2026-10-31T05:00:07Z", "message": {"role": "user", "content": "rules"}}`,
		`{"type": "user", "timestamp": "2026-10-31T05:00:08Z", "message": {"role": "user", "content": "<command-name>/clear"}}`,
		line("11.000", "[Request interrupted by user]"),
		line("12.000", "[Request interrupted by user for tool use]"),
		line("13.000", "[Request interrupted by user] use 8080"),
		line("14.000", "[Request interrupted by user for tool use] use 8080"),
		`{"type": "user", "isSidechain": true, "timestamp": "2026-10-31T05:00:09Z", "message": {"role": "user", "content": "a sub-agent"}}`,
		`{"type": "user", "message": {"role": "user", "content": "no date"}}`,
		`{"type": "user", "timestamp": "2026-10-31T05:00:10Z", "message": {"role": "user", "content": "cut \ud83d"}}`,
		`half a li`}, "\n"))
	write(filepath.Join(state, "input-acme.jsonl"), strings.Join([]string{
		`{"harness": "codex", "conversation": "conv-1", "text": "the first", "after": 0, "source": "ak"}`,
		`{"harness": "claude", "conversation": "conv-0", "text": "the first", "after": 0, "source": "ak"}`,
		`{"harness": "claude", "conversation": "conv-1", "text": "the first", "after": 1, "source": "ak"}`,
		`{"harness": "claude", "conversation": "conv-1", "text": "the first", "source": "ak"}`,
		`{"harness": "claude", "conversation": "conv-1", "text": "ak typed this", "after": 0, "source": "ak"}`,
		`{"harness": "claude", "conversation": "conv-1", "text": "the owner relayed this", "after": 0, "source": "owner"}`}, "\n")+"\n")
	const start = 1793422800
	said, err := OwnerSaid("acme")
	want := []float64{start + 1, start + 3, start + 4, start + 5, start + 10, start + 13, start + 14}
	if err != nil || !slices.Equal(said, want) {
		t.Fatalf("%v, %v, want %v", said, err, want)
	}
	// receipts that cannot be read say nothing of whose a line is: an error where it is asked
	// strictly, none of the owner's otherwise
	receipts := filepath.Join(state, "input-acme.jsonl")
	if os.Remove(receipts) != nil || os.Mkdir(receipts, 0o700) != nil {
		t.Fatal(receipts)
	}
	if _, messages, err := OwnerMessages("acme"); err == nil || errors.Is(err, ErrUnread) || messages != nil {
		t.Errorf("unreadable receipts: %v, %v", messages, err)
	}
	if said, err := OwnerSaid("acme"); said != nil || err != nil {
		t.Errorf("unreadable receipts: %v, %v", said, err)
	}

	if said, err := OwnerSaid("nobody"); said != nil || err != nil {
		t.Errorf("a seat with no record: %v, %v", said, err)
	}
	write(filepath.Join(state, "session-beta.json"), `{"orchestrator": "opus", "cwd": "/code/beta"}`)
	if said, err := OwnerSaid("beta"); said != nil || err != nil {
		t.Errorf("a record naming no conversation: %v, %v", said, err)
	}
	write(filepath.Join(state, "session-gamma.json"), `{"orchestrator": "no such model", "cwd": "/code/gamma", "conversation": "c"}`)
	if _, err := OwnerSaid("gamma"); !errors.Is(err, ErrUnread) {
		t.Errorf("a harness Go does not read: %v", err)
	}
}

// A receipt naming the conversation the seat left takes ak's line where it landed, in the one the
// seat is on now, for the owner's words and the done check alike; the owner's identical later
// line stays theirs.
func TestAkLineInAnotherConversationOfTheSeatIsNotTheOwners(t *testing.T) {
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
	line := func(at, text string) string {
		return `{"type": "user", "timestamp": "2026-11-05T10:00:0` + at + `Z", "message": {"role": "user", "content": "` + text + `"}}` + "\n"
	}
	state, chats := filepath.Join(home, ".agentkit", "state"), filepath.Join(home, ".claude", "projects", "-code-acme")
	write(filepath.Join(home, ".agentkit", "config.toml"),
		"[models.mid]\nharness = 'claude'\nmodel = 'acme-mid'\neffort = 'high'\nprovider = 'test'\n[providers.test]\nmode = 'subscription'\n")
	write(filepath.Join(state, "session-acme.json"), `{"orchestrator": "mid", "cwd": "/code/acme", "conversation": "conv-now",
		"left": [{"harness": "claude", "conversation": "conv-before"}]}`)
	write(filepath.Join(chats, "conv-before.jsonl"), line("1", "Build the acme report."))
	write(filepath.Join(chats, "conv-now.jsonl"), line("3", "Continue the acme report.")+line("4", "Continue the acme report."))
	const start = 1793872800
	// ak's line, typed at 02 after the one message the conversation it names held then
	write(filepath.Join(state, "input-acme.jsonl"), `{"harness": "claude", "conversation": "conv-before", "after": 1, `+
		`"at": 1793872802.0, "text": "Continue the acme report.", "source": "ak"}`+"\n")
	if conversation, said, err := OwnerMessages("acme"); conversation != "conv-now" || len(said) != 1 || said[0].At != start+4 || err != nil {
		t.Fatalf("%q, %v, %v", conversation, said, err)
	}
	had, err := Conversations("acme", true)
	if err != nil || len(had) != 2 || len(had[0].Messages) != 1 || len(had[1].Messages) != 1 || had[1].Messages[0].At != start+4 {
		t.Fatalf("%#v, %v", had, err)
	}
}
