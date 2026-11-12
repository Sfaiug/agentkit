package plan

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"agentkit/internal/host"
	"agentkit/internal/notify"
	"agentkit/internal/run"
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
		had, err := notify.Conversations("acme", true)
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
	kept := filepath.Join(state, "conversations", "claude-conv-1.jsonl")
	write(kept, said("01", "Add a retry button."))
	owes(true, "a transcript Claude deleted that ak's link keeps")
	os.Remove(kept)

	// a conversation the seat left is read under the directory and login it was written under
	write(filepath.Join(state, "session-acme.json"), `{"orchestrator": "opus", "cwd": "/code/acme", "conversation": "conv-2", "left": [{"harness": "claude", "conversation": "conv-1", "cwd": "/code/acme-before", "account": "previous"}]}`)
	write(filepath.Join(home, ".claude-previous", "projects", "-code-acme-before", "conv-1.jsonl"), said("01", "Add a retry button."))
	owes(true, "said in a conversation it left")

	write(filepath.Join(state, "session-acme.json"), `{"orchestrator": "astra", "cwd": "/code/acme", "conversation": "thread-1"}`)
	if _, err := Finished("acme"); !errors.Is(err, ErrUnread) {
		t.Errorf("a harness whose answers Go does not read: %v", err)
	}
	// a harness whose receipt Go reads less strictly than Python is Python's before any read of
	// it follows its launch to the session Muse's registry has since moved it to, and keeps that
	token := strings.Repeat("a", 32)
	receipt := filepath.Join(state, "muse-launch-"+token)
	write(filepath.Join(state, "session-acme.json"), `{"orchestrator": "spark", "cwd": "/code/acme", "muse_launch": "`+token+`"}`)
	write(filepath.Join(receipt, "session"), "before-new")
	t.Setenv("XDG_DATA_HOME", filepath.Join(home, "share"))
	if birth, born := host.ReadIdentity(os.Getpid()); born {
		write(filepath.Join(receipt, "lineage"), run.Line(run.Fields("processes", []any{[]any{run.Number(strconv.Itoa(os.Getpid())),
			run.Fields("boot", birth.Boot, "ticks", int(birth.Ticks), "started_at", birth.StartedAt)}}, "earlier", []any{})))
		write(filepath.Join(home, "share", "muse", "runtime", "muse", "sessions", "after-new.json"),
			run.Line(run.Fields("session_id", "after-new", "process_generation_hint", "pid="+strconv.Itoa(os.Getpid()))))
	}
	_, err := Finished("acme")
	if session, _ := os.ReadFile(filepath.Join(receipt, "session")); !errors.Is(err, ErrUnread) || string(session) != "before-new" {
		t.Errorf("a harness Go reads less strictly than Python: %v, its receipt now %q", err, session)
	}
}

// A listing whose proof would leave the plan owing its done check asks first whether Go makes the
// check: where Python does, nothing is written, so Python proves and ticks the line itself; where
// Go does, it ticks and lists it, owing the check.  With nothing said, it owes none, and asks none.
func TestAListingOwingTheDoneCheckAsksWhetherGoMakesItBeforeWritingAnything(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	git := func(dir string, args ...string) string {
		t.Helper()
		out, err := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=acme", "-c", "user.email=acme@example.com"}, args...)...).CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	write := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil || os.WriteFile(path, []byte(text), 0o600) != nil {
			t.Fatal(path)
		}
	}
	repo, remote, state := filepath.Join(home, "code", "acme"), filepath.Join(home, "origin.git"), filepath.Join(home, ".agentkit", "state")
	write(filepath.Join(repo, "README"), "acme\n")
	git(home, "init", "-q", "--bare", "--initial-branch=main", remote)
	git(repo, "init", "-q", "--initial-branch=main")
	git(repo, "add", "README")
	git(repo, "commit", "-qm", "init")
	base := git(repo, "rev-parse", "--short=12", "HEAD")
	write(filepath.Join(repo, "parser.txt"), "parser\n")
	git(repo, "add", "parser.txt")
	git(repo, "commit", "-qm", "ship the parser")
	git(repo, "remote", "add", "origin", remote)
	git(repo, "push", "-q", "-u", "origin", "main")
	write(filepath.Join(state, "session-acme.json"), `{"orchestrator": "opus", "cwd": "`+repo+`", "conversation": "conv-1"}`)
	chat := filepath.Join(home, ".claude", "projects", strings.Map(func(r rune) rune {
		if r < '0' || r > '9' && r < 'A' || r > 'Z' && r < 'a' || r > 'z' {
			return '-'
		}
		return r
	}, repo), "conv-1.jsonl")
	said := `{"type": "user", "timestamp": "2026-11-05T10:00:00Z", "message": {"role": "user", "content": "Ship the parser."}}` + "\n"
	write(chat, said)
	plan := filepath.Join(state, "plan-acme.md")
	line := func(check string) string {
		return "- [ ] Ship the parser · check: `" + check + "` · " + repo + "#" + base + " · written 2026-11-05 10:05 on " + base + "\n"
	}
	pythons := func(current string) error {
		if current != "acme" {
			t.Errorf("asked of %q", current)
		}
		return ErrUnread
	}
	unasked := func(string) error {
		t.Error("asked with nothing owed")
		return nil
	}
	original := line("test -f parser.txt")
	write(plan, original)
	_, _, err := List(context.Background(), "acme", pythons)
	if data, _ := os.ReadFile(plan); !errors.Is(err, ErrUnread) || string(data) != original {
		t.Fatalf("the check owed, Python's: %v, the plan now %q", err, data)
	}
	box, owes, err := List(context.Background(), "acme", func(string) error { return nil })
	if err != nil || !owes || len(box) != 1 || !strings.HasPrefix(box[0], "- [x] Ship the parser") {
		t.Fatalf("the check owed, Go's: %q, %v, %v", box, owes, err)
	}
	write(chat, "")
	write(plan, original)
	box, owes, err = List(context.Background(), "acme", unasked)
	if err != nil || owes || len(box) != 1 || !strings.HasPrefix(box[0], "- [x] Ship the parser") {
		t.Fatalf("nothing said: %q, %v, %v", box, owes, err)
	}

	// a delivery counted while the listing verified has it verify again (settle): there too, a
	// plan it would leave owing the check is left unwritten, and the count with it
	marker, owed := filepath.Join(home, "verified-once"), filepath.Join(state, "unverified-acme.txt")
	flaky := line("test -f " + marker + " || { touch " + marker + " && echo 1 > " + owed + " && false; }")
	for _, owner := range []string{said, ""} {
		write(chat, owner)
		write(plan, flaky)
		os.Remove(marker)
		os.Remove(owed)
		carried := unasked
		if owner != "" {
			carried = pythons
		}
		box, _, err := List(context.Background(), "acme", carried)
		data, _ := os.ReadFile(plan)
		count, gone := os.ReadFile(owed)
		if owner != "" && (!errors.Is(err, ErrUnread) || string(data) != flaky || string(count) != "1\n") {
			t.Errorf("settled, the check owed: %v, the plan now %q, %q owed", err, data, count)
		}
		if owner == "" && (err != nil || len(box) != 1 || !strings.HasPrefix(box[0], "- [x] Ship the parser") || gone == nil) {
			t.Errorf("settled, nothing said: %q, %v, %q owed", box, err, count)
		}
	}
}
