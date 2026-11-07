package harness

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
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

func TestMuseReceiptFollowsItsLaunchThroughNewIntoTheReopen(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("a process's birth is read off Linux's /proc")
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	data := filepath.Join(home, "data[acme]") // a path, though it reads as a pattern
	t.Setenv("XDG_DATA_HOME", data)
	registry := filepath.Join(data, "muse", "runtime", "muse", "sessions")
	program := filepath.Join(t.TempDir(), "muse")
	if os.MkdirAll(registry, 0o700) != nil || os.MkdirAll(filepath.Join(home, ".agentkit", "state"), 0o700) != nil ||
		os.WriteFile(program, []byte(fakeMuse), 0o700) != nil {
		t.Fatal("no fake Muse")
	}
	register := func(session string, pid int) {
		entry := fmt.Sprintf(`{"session_id": %q, "process_generation_hint": "pid=%d"}`, session, pid)
		if err := os.WriteFile(filepath.Join(registry, session+".json"), []byte(entry), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	owned := func(fields *run.Object, want string) {
		t.Helper()
		if got, known := Owned("muse", map[string]any{"muse_launch": fields.Str("muse_launch")}); got != want || !known {
			t.Fatalf("the seat owns %q, want %q", got, want)
		}
	}

	// a fresh launch: a receipt of its own, named in its record and handed to its hooks
	launched, words, err := Launched("muse", "acme", home, "", run.NewObject())
	if err != nil || len(words) != 1 || !strings.HasPrefix(words[0], museReceiptEnv+"=") {
		t.Fatalf("launch words %q: %v", words, err)
	}
	receipt := strings.TrimPrefix(words[0], museReceiptEnv+"=")
	owned(launched, "")
	register("next-door", os.Getpid()) // already listed, under a process of the launch's lineage
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
		if _, err := os.Stat(filepath.Join(receipt, "lineage")); err == nil {
			break
		} else if time.Now().After(deadline) {
			t.Fatalf("no SessionStart reached the receipt by hook %q", hook)
		}
	}
	owned(launched, "opened")

	// a later SessionStart into the same receipt: the first stands
	again := exec.Command("sh", "-c", hook)
	again.Stdin = strings.NewReader(`{"hook_event_name": "SessionStart", "session_id": "later"}`)
	if err := again.Run(); err != nil {
		t.Fatal(err)
	}
	owned(launched, "opened")

	// Muse's /new fires no hook: its registry moves the launch's Muse to the next session
	register("opened", muse.Process.Pid)
	owned(launched, "opened")
	os.Remove(filepath.Join(registry, "opened.json"))
	register("after-new", muse.Process.Pid)
	owned(launched, "after-new")
	// the line the launch opened on went into the session it reported, and stays there
	deferred := run.Fields("conversation", nil, "launch", run.Fields("muse_launch", launched.Str("muse_launch")))
	if went := WentInto("muse", deferred); went != "opened" {
		t.Fatalf("the launch's first line went into %q", went)
	}

	// that Muse gone, its pid another's, the receipt keeps the last session it was given
	muse.Process.Kill()
	muse.Wait()
	os.Remove(filepath.Join(registry, "after-new.json"))
	register("recycled", muse.Process.Pid)
	owned(launched, "after-new")

	// the reopen resumes it on a receipt of its own, and the one it replaced is gone
	if opened, known := Opened("muse", map[string]any{"muse_launch": launched.Str("muse_launch")}); !opened || !known {
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
	if err != nil || strings.TrimPrefix(words[0], museReceiptEnv+"=") == receipt {
		t.Fatalf("the reopen shares its receipt %q: %v", words, err)
	}
	owned(relaunched, "after-new")
	if err := Retire("muse", launched); err != nil {
		t.Fatal(err)
	}
	if gone, err := filepath.Glob(receipt + "*"); len(gone) > 0 || err != nil {
		t.Fatalf("the replaced receipt is left: %q", gone)
	}
}
