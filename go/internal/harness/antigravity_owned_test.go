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
	// a process carrying that token, holding each conversation's files open beside agy's summaries,
	// once it runs: /proc reads a process's environment empty until its exec has set it up, after
	// Start returns, so it is asked only once it echoes a line back
	agy := func(token string, conversations ...string) *exec.Cmd {
		held := exec.Command("cat")
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
		in, err := held.StdinPipe()
		if err != nil {
			t.Fatal(err)
		}
		out, err := held.StdoutPipe()
		if err != nil {
			t.Fatal(err)
		}
		if err := held.Start(); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { held.Process.Kill(); held.Wait() })
		if _, err := in.Write([]byte("\n")); err != nil {
			t.Fatal(err)
		}
		if _, err := out.Read(make([]byte, 1)); err != nil {
			t.Fatal(err)
		}
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
	// whoever asks, a listing among them, learns what the seat owns and writes nothing
	asked := func(name string, want string) {
		t.Helper()
		before, _ := os.ReadFile(path(name))
		data, _ := run.Decode(before)
		owns(record(name), want)
		if _, known := For("antigravity").Reconciled(name, data.(*run.Object)); !known {
			t.Fatalf("%s: the listing does not read it", name)
		}
		if after, _ := os.ReadFile(path(name)); string(after) != string(before) {
			t.Fatalf("asking wrote %s", after)
		}
	}

	acme := seat("acme")
	asked("acme", "")
	running := agy(acme, "c-acme")
	asked("acme", "c-acme")
	before := record("acme") // a caller's copy from before the claim
	owns(before, "c-acme")
	Claim(true) // the command ends, carried through
	if kept, _ := run.ReadJSON(path("acme")); !run.Equal(kept.Get("antigravity_open"), run.Fields("launch", acme, "conversation", "c-acme")) {
		t.Fatalf("written down: %s", run.Encode(kept))
	}
	running.Process.Kill()
	running.Wait()
	owns(before, "c-acme") // the claim outlives the process
	asked("acme", "c-acme")

	agy(seat("beta"), "c-acme") // another seat's
	owns(record("beta"), "")
	agy(seat("gamma"), "c-one", "c-two") // a guess between two
	asked("gamma", "")
	seat("acme") // relaunched: the stale launch's agy runs on
	agy(acme, "c-later")
	owns(record("acme"), "")

	// one learns at a time, waiting for the claim another seat is making, from the records as they
	// then stand
	claiming, err := lock.Wait(context.Background(), filepath.Join(state, "antigravity-claim.lock"))
	if err != nil {
		t.Fatal(err)
	}
	agy(seat("delta"), "c-shared")
	waiting := record("delta")
	answer := make(chan string)
	go func() { conversation, _ := Owned("antigravity", waiting); answer <- conversation }()
	time.Sleep(200 * time.Millisecond) // long enough to read the records, were it not waiting
	antigravityClaim(record("gamma")["antigravity_launch"].(string), "c-shared")
	claiming.Close()
	if got := <-answer; got != "" {
		t.Fatalf("delta took %q, gamma's claim", got)
	}

	// what a command learned is written down only where it still stands as the command ends: not
	// for a seat relaunched since, nor a conversation another seat's claim took meanwhile, nor one a
	// launcher resumed elsewhere while the claim waited for the record's lock
	agy(seat("epsilon"), "c-epsilon")
	agy(seat("zeta"), "c-zeta")
	agy(seat("eta"), "c-eta")
	for name, want := range map[string]string{"epsilon": "c-epsilon", "zeta": "c-zeta", "eta": "c-eta"} {
		owns(record(name), want)
	}
	seat("epsilon")
	antigravityClaim(record("beta")["antigravity_launch"].(string), "c-zeta")
	unwritten := map[string][]byte{}
	for _, name := range []string{"epsilon", "zeta", "eta"} {
		unwritten[name], _ = os.ReadFile(path(name))
	}
	recording, err := lock.Wait(context.Background(), filepath.Join(state, ".session-eta.lock"))
	if err != nil {
		t.Fatal(err)
	}
	claimed := make(chan bool)
	go func() { Claim(true); close(claimed) }()
	time.Sleep(200 * time.Millisecond) // long enough to write eta's claim, were it not waiting
	if err := os.WriteFile(path("theta"), []byte(`{"id_source": "launcher", "conversation": "c-eta"}`+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	recording.Close()
	<-claimed
	for name, before := range unwritten {
		if after, _ := os.ReadFile(path(name)); string(after) != string(before) {
			t.Fatalf("%s's claim was written: %s", name, after)
		}
	}
}
