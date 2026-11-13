package harness

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// TestMain lets this test binary be the command a launch's hooks run, `<ak> adapter <root> <harness>
// hook`, which hands its event to HookEvent as ak's adapter verb does.
func TestMain(m *testing.M) {
	if len(os.Args) == 5 && os.Args[1] == "adapter" && os.Args[4] == "hook" {
		payload, _ := io.ReadAll(os.Stdin)
		read, _ := run.Decode(payload)
		event, _ := read.(*run.Object)
		HookEvent(os.Args[3], event, io.Discard, nil, nil)
		os.Exit(0)
	}
	os.Exit(m.Run())
}

// fakeMuse answers its schema with hook events, and as the TUI runs the SessionStart hook its
// launch handed it, for the session it opened, then lives on as itself.
const fakeMuse = `#!/bin/sh
[ "$1" = schema ] && exec printf '"notification"' >"$4/schema.json"
printf '{"hook_event_name": "SessionStart", "session_id": "%s"}' "$SESSION" | sh -c "$HOOK"
exec sleep 60
`

// A launch's receipt keeps the session its SessionStart reported, the first standing; past `/new`,
// which fires no hook, a turn's end names the session the seat goes on in (museFollows), which a
// Stop's claim writes into the record, and the reopen resumes that one on a receipt of its own.
func TestMuseReceiptKeepsItsLaunchsSessionIntoTheReopen(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	data := filepath.Join(home, "data[acme]") // a path, though it reads as a pattern
	t.Setenv("XDG_DATA_HOME", data)
	program := filepath.Join(t.TempDir(), "muse")
	if os.MkdirAll(filepath.Join(home, ".agentkit", "state"), 0o700) != nil ||
		os.WriteFile(program, []byte(fakeMuse), 0o700) != nil {
		t.Fatal("no fake Muse")
	}
	owned := func(record map[string]any, want string) {
		t.Helper()
		if got, known := Owned("muse", record); got != want || !known {
			t.Fatalf("the seat owns %q, want %q", got, want)
		}
	}

	// a fresh launch: a receipt of its own, named in its record and handed to its hooks, and no
	// session the record followed to before it
	launched, words, err := Launched("muse", "acme", home, "", run.NewObject())
	if err != nil || len(words) != 1 || !strings.HasPrefix(words[0], museReceiptEnv+"=") ||
		!launched.Has("conversation") || launched.Get("conversation") != nil {
		t.Fatalf("launch %s, words %q: %v", run.Line(launched), words, err)
	}
	receipt := strings.TrimPrefix(words[0], museReceiptEnv+"=")
	token := launched.Str("muse_launch")
	owned(map[string]any{"muse_launch": token}, "")
	line := museSeatWords([]string{program}, append(os.Environ(), "AGENTKIT_SESSION=acme", words[0]))
	hook := ""
	for i, word := range line {
		if payload, ok := strings.CutPrefix(word, "hooks.SessionStart="); ok && line[i-1] == "-c" {
			var groups []struct{ Hooks []struct{ Command string } }
			json.Unmarshal([]byte(payload), &groups)
			hook = groups[0].Hooks[0].Command
		}
	}
	muse := exec.Command(program)
	muse.Env = append(os.Environ(), "HOOK="+hook, "SESSION=opened")
	if err := muse.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { muse.Process.Kill(); muse.Wait() })
	for deadline := time.Now().Add(30 * time.Second); ; time.Sleep(20 * time.Millisecond) {
		if _, err := os.Stat(filepath.Join(receipt, "session")); err == nil {
			break
		} else if time.Now().After(deadline) {
			t.Fatalf("no SessionStart reached the receipt by hook %q", hook)
		}
	}
	owned(map[string]any{"muse_launch": token}, "opened")

	// a later SessionStart into the same receipt: the first stands
	again := exec.Command("sh", "-c", hook)
	again.Stdin = strings.NewReader(`{"hook_event_name": "SessionStart", "session_id": "later"}`)
	if err := again.Run(); err != nil {
		t.Fatal(err)
	}
	owned(map[string]any{"muse_launch": token}, "opened")

	// past /new, a Stop names the session its turn ran in, once Muse logs it, and moves the seat;
	// an Interrupt's is kept, and no other event names one
	log := filepath.Join(data, "muse", "sessions", "2026", "10", "24", "after-new", "session.jsonl")
	ended := func(event string) *Followed {
		return museFollows(run.Fields("hook_event_name", event, "session_id", "after-new"))
	}
	if to := ended("Stop"); to == nil || to.Transcript != nil || to.Keep {
		t.Fatalf("a Stop before its session's log follows %+v", to)
	}
	if os.MkdirAll(filepath.Dir(log), 0o700) != nil || os.WriteFile(log, nil, 0o600) != nil {
		t.Fatal("no log")
	}
	if to := ended("Stop"); to == nil || to.Transcript != log || to.Filed("after-new") != log ||
		to.Keep || to.Source != museHook || !to.Client([]string{"/opt/muse/muse-bin-1.4.12", "resume"}) ||
		to.Client([]string{"/usr/bin/sh", "-c", "muse"}) {
		t.Fatalf("a Stop follows %+v", to)
	}
	if to := ended("Interrupt"); to == nil || !to.Keep {
		t.Fatalf("an Interrupt follows %+v", to)
	}
	if to := ended("Notification"); to != nil {
		t.Fatalf("a Notification follows %+v", to)
	}
	// the record a Stop's claim wrote names the session the seat goes on in; one the record kept
	// from another harness names none of Muse's
	owned(map[string]any{"muse_launch": token, "id_source": museHook, "conversation": "after-new"}, "after-new")
	owned(map[string]any{"muse_launch": token, "id_source": "launcher", "conversation": "thread"}, "opened")
	// the line the launch opened on went into the session it reported, as one a receipt the registry
	// moved on before keeps it as `reported`
	deferred := run.Fields("conversation", nil, "launch", run.Fields("muse_launch", token))
	if went := WentInto("muse", deferred); went != "opened" {
		t.Fatalf("the launch's first line went into %q", went)
	}
	if os.WriteFile(filepath.Join(receipt, "reported"), []byte("before-new"), 0o600) != nil {
		t.Fatal("no reported session")
	}
	if went := WentInto("muse", deferred); went != "before-new" {
		t.Fatalf("the moved launch's first line went into %q", went)
	}

	// the reopen resumes it on a receipt of its own, and the one it replaced is gone
	if opened, known := Opened("muse", map[string]any{"muse_launch": token}); !opened || !known {
		t.Fatalf("the reported session reads unopened (%v, %v)", opened, known)
	}
	rulebook := filepath.Join(home, "rulebook.md")
	os.WriteFile(rulebook, []byte("rules"), 0o600)
	t.Setenv("AGENTKIT_RULEBOOK", rulebook)
	var out bytes.Buffer
	if museInteractive(home, []string{"spark", "high", "after-new"}, &out, io.Discard) != 0 ||
		!strings.Contains(out.String(), " muse resume after-new ") {
		t.Fatalf("the reopen runs %q", out.String())
	}
	relaunched, words, err := Launched("muse", "acme", home, "after-new", launched)
	if err != nil || strings.TrimPrefix(words[0], museReceiptEnv+"=") == receipt || relaunched.Has("conversation") {
		t.Fatalf("the reopen shares its receipt %q, or drops its session %s: %v", words, run.Line(relaunched), err)
	}
	owned(map[string]any{"muse_launch": relaunched.Str("muse_launch")}, "after-new")
	if err := Retire("muse", launched); err != nil {
		t.Fatal(err)
	}
	if gone, err := filepath.Glob(receipt + "*"); len(gone) > 0 || err != nil {
		t.Fatalf("the replaced receipt is left: %q", gone)
	}
}
