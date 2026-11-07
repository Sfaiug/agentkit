package harness

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

func TestAnAntigravitySeatClaimsTheOneStoreItsAgyHoldsOpen(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("a process's open files are read off Linux's /proc")
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	state, store := filepath.Join(home, ".agentkit", "state"), antigravityConversations()
	if os.MkdirAll(state, 0o700) != nil || os.MkdirAll(store, 0o700) != nil {
		t.Fatal("no home")
	}
	path := func(name string) string { return filepath.Join(state, "session-"+name+".json") }
	// a seat launched as Go launches one, and the token its agy carries
	seat := func(name string) string {
		fields, env := LaunchExtras("antigravity")
		if err := os.WriteFile(path(name), []byte(run.Encode(run.SetAll(fields, "orchestrator", "gemini"))+"\n"), 0o600); err != nil || len(env) != 1 {
			t.Fatal(err, env)
		}
		return strings.TrimPrefix(env[0], antigravityLaunchEnv+"=")
	}
	// a process carrying that token, holding each conversation's files open beside agy's summaries
	agy := func(token string, conversations ...string) *exec.Cmd {
		held := exec.Command("sleep", "60")
		held.Env = append(os.Environ(), antigravityLaunchEnv+"="+token)
		files := []string{filepath.Join("..", "conversation_summaries.db")}
		for _, conversation := range conversations {
			files = append(files, conversation+".db", conversation+".db-wal", conversation+".db-shm")
		}
		for _, name := range files {
			file, err := os.OpenFile(filepath.Join(store, name), os.O_CREATE|os.O_RDWR, 0o600)
			if err != nil {
				t.Fatal(err)
			}
			defer file.Close()
			held.ExtraFiles = append(held.ExtraFiles, file)
		}
		if err := held.Start(); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { held.Process.Kill(); held.Wait() })
		return held
	}
	record := func(name string) map[string]any {
		_, record, err := config.ResolveSession(name)
		if err != nil {
			t.Fatal(err)
		}
		return record
	}
	owns := func(record map[string]any, want string) {
		t.Helper()
		if got, known := Owned("antigravity", record); got != want || !known {
			t.Fatalf("the seat owns %q, want %q", got, want)
		}
	}
	// an admission learns what the seat owns, and a listing reads only a seat learning none; neither
	// writes anything
	asked := func(name string, want string, ready bool) {
		t.Helper()
		before, _ := os.ReadFile(path(name))
		data, _ := run.Decode(before)
		if got, known := Owning("antigravity", record(name)); got != want || !known {
			t.Fatalf("%s: an admission learns %q, want %q", name, got, want)
		}
		if _, known := For("antigravity").Reconciled(name, data.(*run.Object)); known != ready {
			t.Fatalf("%s: the listing reads it: %v, want %v", name, known, ready)
		}
		if after, _ := os.ReadFile(path(name)); string(after) != string(before) {
			t.Fatalf("asking wrote %s", after)
		}
	}

	acme := seat("acme")
	asked("acme", "", true)
	running := agy(acme, "c-acme")
	asked("acme", "c-acme", false)
	before := record("acme") // a caller's copy from before the claim
	owns(before, "c-acme")
	if kept, _ := run.ReadJSON(path("acme")); !run.Equal(kept.Get("antigravity_open"), run.Fields("launch", acme, "conversation", "c-acme")) {
		t.Fatalf("written down: %s", run.Encode(kept))
	}
	running.Process.Kill()
	running.Wait()
	owns(before, "c-acme")
	asked("acme", "c-acme", false)

	agy(seat("beta"), "c-acme") // another seat's
	owns(record("beta"), "")
	agy(seat("gamma"), "c-one", "c-two") // a guess between two
	owns(record("gamma"), "")
	seat("acme") // relaunched: the stale launch's agy runs on
	agy(acme, "c-later")
	owns(record("acme"), "")

	// a claim waits for the one another seat is making, and takes the records as they then stand
	claiming, err := lock.Wait(context.Background(), filepath.Join(state, "antigravity-claim.lock"))
	if err != nil {
		t.Fatal(err)
	}
	agy(seat("delta"), "c-shared")
	waiting := record("delta")
	answer := make(chan string)
	go func() { conversation, _ := Owned("antigravity", waiting); answer <- conversation }()
	time.Sleep(200 * time.Millisecond) // long enough to read the records, were it not waiting
	if err := antigravitySaw("gamma", run.Fields("launch", record("gamma")["antigravity_launch"], "conversation", "c-shared")); err != nil {
		t.Fatal(err)
	}
	claiming.Close()
	if got := <-answer; got != "" {
		t.Fatalf("delta took %q, gamma's claim", got)
	}
}
