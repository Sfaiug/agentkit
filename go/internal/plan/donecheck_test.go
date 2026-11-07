package plan

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/notify"
)

// A plan with every line done owes its done check while what its owner said stands unchecked
// (done_check.owed): until a check that found no gap kept what it read, and again once they say
// more.  Not with nothing said, nor with the check off whatever model it names; a record that is
// there and cannot be read holds the seat, and one Go does not read is Python's.  Only a seat
// someone is in owes it (OwesLine).
func TestAFinishedPlanOwesItsCheckUntilOneReadWhatItsOwnerSaid(t *testing.T) {
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
	chat := filepath.Join(home, ".claude", "projects", "-code-acme", "conv-1.jsonl")
	said := func(at, text string) string {
		return `{"type": "user", "timestamp": "2026-10-31T05:00:` + at + `Z", "message": {"role": "user", "content": "` + text + `"}}` + "\n"
	}
	write(filepath.Join(state, "session-acme.json"), `{"orchestrator": "opus", "cwd": "/code/acme", "conversation": "conv-1"}`)
	write(filepath.Join(state, "plan-acme.md"), "- [x] Merge the parser\n")
	write(chat, "")
	owes := func(want bool, why string) {
		t.Helper()
		finished, err := Finished("acme")
		line, owed, lineErr := OwedLine("acme")
		alone, aloneErr := OwesLine("acme")
		if err != nil || lineErr != nil || aloneErr != nil || alone || finished == want || owed != want || want && line != owedCheck {
			t.Errorf("%s: finished %v, owed %v %q, a line alone %v (%v, %v, %v)", why, finished, owed, line, alone, err, lineErr, aloneErr)
		}
	}
	owes(false, "nothing said")
	write(chat, said("01", "Add a retry button."))
	owes(true, "said, never checked")
	keep := func() {
		t.Helper()
		had, err := notify.Conversations("acme")
		_, owner, owned := OwnerWords(had)
		if err != nil || owned != nil {
			t.Fatal(err, owned)
		}
		write(filepath.Join(state, "checked-acme.txt"), Fingerprint(owner, []string{"- [x] Merge the parser"})+"\n")
	}
	keep()
	owes(false, "checked")
	write(chat, said("01", "Add a retry button.")+said("02", "And a receipt."))
	owes(true, "said more since")
	keep()
	owes(false, "checked again")

	write(filepath.Join(home, ".agentkit", "config.toml"), "[done_check]\non = false\nmodel = \"nobody\"\n")
	os.Remove(filepath.Join(state, "checked-acme.txt"))
	owes(false, "the check off")
	os.Remove(filepath.Join(home, ".agentkit", "config.toml"))
	owes(true, "the check on again")

	if os.Remove(chat) != nil || os.Mkdir(chat, 0o700) != nil {
		t.Fatal(chat)
	}
	owes(true, "a transcript that cannot be read")
	os.Remove(chat)
	owes(false, "a transcript that is gone")

	write(filepath.Join(state, "session-acme.json"), `{"orchestrator": "astra", "cwd": "/code/acme", "conversation": "thread-1"}`)
	if _, err := Finished("acme"); !errors.Is(err, ErrUnread) {
		t.Errorf("a harness whose answers Go does not read: %v", err)
	}
}
