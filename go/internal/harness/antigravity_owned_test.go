package harness

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"agentkit/internal/config"
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
	keep := func(name string, record *run.Object) {
		if err := os.WriteFile(path(name), []byte(run.Encode(record)+"\n"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	// a seat launched as Go launches one, and the token its agy carries
	seat := func(name string) string {
		fields, env := LaunchExtras("antigravity")
		keep(name, run.SetAll(fields, "orchestrator", "gemini"))
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
	// whoever asks, a reopen's admission or a dry run among them, writes nothing
	owns := func(name string, record map[string]any, want string) {
		t.Helper()
		before, _ := os.ReadFile(path(name))
		if got, known := Owned("antigravity", record); got != want || !known {
			t.Fatalf("%s owns %q, want %q", name, got, want)
		}
		if after, _ := os.ReadFile(path(name)); string(after) != string(before) {
			t.Fatalf("asking wrote %s", after)
		}
	}
	// a listing reads only a seat learning none
	listed := func(name string, ready bool) {
		t.Helper()
		data, _ := run.ReadJSON(path(name))
		if _, known := For("antigravity").Reconciled(name, data); known != ready {
			t.Fatalf("%s: the listing reads it: %v, want %v", name, known, ready)
		}
	}

	acme := seat("acme")
	owns("acme", record("acme"), "")
	listed("acme", true)
	running := agy(acme, "c-acme")
	before := record("acme") // a caller's copy from before Python's claim
	owns("acme", before, "c-acme")
	listed("acme", false)
	claimed, _ := run.ReadJSON(path("acme"))
	keep("acme", run.SetAll(claimed, "antigravity_open", run.Fields("launch", acme, "conversation", "c-acme")))
	running.Process.Kill()
	running.Wait()
	owns("acme", before, "c-acme") // the claim outlives the process
	listed("acme", false)

	agy(seat("beta"), "c-acme") // another seat's
	owns("beta", record("beta"), "")
	agy(seat("gamma"), "c-one", "c-two") // a guess between two
	owns("gamma", record("gamma"), "")
	listed("gamma", true)
	seat("acme") // relaunched: the stale launch's agy runs on
	agy(acme, "c-later")
	owns("acme", record("acme"), "")
}
