package cli

import (
	"bytes"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/sqlite"
)

// A seat whose current conversation is named by a live Antigravity launch, or by its hook, is
// checked by `ak orch check` as Python checks it: the launch's conversation learned and written
// down, its store read strictly; the hook's read with what the seat left.
func TestOrchCheckChecksALiveAntigravitySeat(t *testing.T) {
	t.Run("a launch whose agy holds one store open", func(t *testing.T) {
		if runtime.GOOS != "linux" {
			t.Skip("a process's open files are read off Linux's /proc")
		}
		home := agyHome(t)
		store := filepath.Join(home, ".gemini", "antigravity-cli", "conversations", "c-acme.db")
		write(t, store, "")
		fields, token := agyLaunched(t, store)
		state := filepath.Join(home, ".agentkit", "state")
		write(t, filepath.Join(state, "session-acme.json"), run.Encode(run.SetAll(fields, "orchestrator", "mid", "cwd", home, "workers", []any{"mid"}))+"\n")
		// a store that holds no steps table cannot be read, as Python's `rows` raises reading it
		var stdout, stderr bytes.Buffer
		if code := Main([]string{"orch", "check", "acme"}, &stdout, &stderr); code != 2 || stdout.Len() != 0 {
			t.Fatalf("got (%d, %q, %q), want exit 2", code, stdout.String(), stderr.String())
		}
		if kept, _ := run.ReadJSON(filepath.Join(state, "session-acme.json")); !run.Equal(kept.Get("antigravity_open"), run.Fields("launch", token, "conversation", "c-acme")) {
			t.Fatalf("written down: %s", run.Encode(kept))
		}
	})

	t.Run("a conversation its hook followed after leaving another", func(t *testing.T) {
		home := agyHome(t)
		state := filepath.Join(home, ".agentkit", "state")
		write(t, filepath.Join(state, "session-acme.json"), `{"orchestrator": "mid", "cwd": "/code/acme", "workers": ["mid"], `+
			`"id_source": "antigravity-hook", "conversation": "c-after", `+
			`"left": [{"harness": "claude", "conversation": "c-before"}]}`+"\n")
		var stdout, stderr bytes.Buffer
		if code := Main([]string{"orch", "check", "acme"}, &stdout, &stderr); code != 0 {
			t.Fatalf("got (%d, %q, %q), want exit 0", code, stdout.String(), stderr.String())
		}
	})
}

// A check Go leaves to Python writes nothing, of a live Antigravity launch whose conversation no
// record holds yet too, which a read learns under the claim's lock: a picture's name, a run's
// title or a checker that is Python's is settled before any conversation is read.
func TestOrchCheckLeftToPythonWritesNothing(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("a process's open files are read off Linux's /proc")
	}
	for name, each := range map[string]struct {
		pictures, run string
		goTurns       bool // whether the home names the adapters folder Go runs the checker's turn from
	}{
		"a picture whose name Go does not keep": {`{"at": 1793872800, "name": "shot-\udcff.png", "data": "aGVsbG8="}` + "\n", "", true},
		"a run whose title Go does not keep":    {"", `{"launched_session": "acme", "title": "\ud800"}`, true},
		"a checker whose turn Python runs":      {"", "", false}, // as in every real home
	} {
		t.Run(name, func(t *testing.T) {
			home := agyHome(t)
			if !each.goTurns {
				t.Setenv("AGENTKIT_ADAPTER_DIR", "")
			}
			store := filepath.Join(home, ".gemini", "antigravity-cli", "conversations", "c-acme.db")
			write(t, store, "")
			db, err := sqlite.Open(store, sqlite3.OPEN_READWRITE|sqlite3.OPEN_CREATE)
			if err == nil {
				err = db.Exec("CREATE TABLE steps (idx integer, step_type integer, status integer, metadata blob, step_payload blob)")
			}
			if err != nil || db.Close() != nil {
				t.Fatal(err)
			}
			fields, _ := agyLaunched(t, store)
			// what the owner asked is in the conversation the seat left, before it launched agy
			write(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"), run.Encode(run.SetAll(fields, "orchestrator", "mid",
				"cwd", "/code/acme", "workers", []any{"mid"}, "left", []any{run.Fields("harness", "claude", "conversation", "c-before")}))+"\n")
			write(t, filepath.Join(home, ".claude", "projects", "-code-acme", "c-before.jsonl"),
				`{"type": "user", "timestamp": "2026-11-05T10:00:00Z", "message": {"role": "user", "content": "Add a retry button."}}`+"\n")
			if each.pictures != "" {
				write(t, filepath.Join(home, ".agentkit", "state", "pictures-acme.jsonl"), each.pictures)
			}
			if each.run != "" {
				write(t, filepath.Join(home, ".agentkit", "runs", "r-fix", "run.json"), each.run)
			}
			before := tree(t, home)
			var out, errOut bytes.Buffer
			if code := Main([]string{"orch", "check", "acme"}, &out, &errOut); code != 3 || out.Len() != 0 || errOut.String() != "ak orch check: not implemented in Go yet\n" {
				t.Fatalf("got (%d, %q, %q), want exit 3", code, out.String(), errOut.String())
			}
			if after := tree(t, home); !reflect.DeepEqual(before, after) {
				var changed []string
				for path := range after {
					if text, had := before[path]; !had || text != after[path] {
						changed = append(changed, path)
					}
				}
				t.Fatalf("it wrote into HOME: %q", changed)
			}
		})
	}
}

// agyHome is a home whose seats run on Antigravity, naming the adapters folder Go runs the
// checker's turn from: none of them is asked.
func agyHome(t *testing.T) string {
	t.Helper()
	home := sandbox(t)
	t.Setenv("AGENTKIT_ADAPTER_DIR", t.TempDir())
	write(t, filepath.Join(home, ".agentkit", "config.toml"),
		"[models.mid]\nharness='antigravity'\nmodel='acme/m'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	return home
}

// agyLaunched is a live Antigravity launch's fields for its seat's record, and its token: an agy
// carrying the token runs, holding store open.
func agyLaunched(t *testing.T, store string) (*run.Object, string) {
	t.Helper()
	fields, env := harness.LaunchExtras("antigravity")
	file, err := os.Open(store)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	agy := exec.Command("cat")
	agy.Env, agy.ExtraFiles = append(os.Environ(), env...), []*os.File{file}
	in, err := agy.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	out, err := agy.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := agy.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { agy.Process.Kill(); agy.Wait() })
	// running once it echoes, its fds in /proc
	if _, err := in.Write([]byte("\n")); err != nil {
		t.Fatal(err)
	}
	if _, err := io.ReadFull(out, make([]byte, 1)); err != nil {
		t.Fatal(err)
	}
	return fields, strings.TrimPrefix(env[0], "AGENTKIT_ANTIGRAVITY_LAUNCH=")
}
