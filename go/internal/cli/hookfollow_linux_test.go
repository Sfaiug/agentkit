package cli

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/run"
	"agentkit/internal/sqlite"
)

const (
	grokRecord = `{"orchestrator": "nova", "conversation": "old-session", "id_source": "launcher", "cwd": "/code/acme"}`
	grokLatch  = `{"session": "acme", "turn": 1, "blocks": 2}`
)

// grokPrompt is the hook's exit on a prompt seat acme's own Grok ran in new-session, the seat's
// record on old-session and its last turn latched, and the files it leaves in state.  tmux opens
// on server, the fake ps on meanwhile, which runs as the claim reads the process table.
func grokPrompt(t *testing.T, name, server, meanwhile string, prepare func(state string)) (code int, state string) {
	t.Helper()
	home := sandbox(t)
	state = filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.nova]\nharness='grokbuild'\nmodel='grok-test'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	write(t, filepath.Join(state, "session-acme.json"), grokRecord)
	write(t, filepath.Join(state, "stop-acme.json"), grokLatch)
	t.Setenv("AGENTKIT_SESSION", "acme")
	t.Setenv("TMUX", "/tmp/acme-test,1,0")
	t.Setenv("TMUX_PANE", "%1")
	t.Setenv("GROK_HOME", "")
	bin := t.TempDir()
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	for name, script := range map[string]string{
		"tmux": "#!/bin/sh\n" + server + "case \"$*\" in\n" +
			"*list-sessions*) printf 'acme\\t1\\n' ;;\n" +
			"*list-panes*) printf 'acme\\t0\\n' ;;\n" +
			"*display-message*socket_path*) printf '/tmp/acme-test\\tacme\\t700\\t%%1\\n' ;;\n" +
			"*) exit 1 ;;\nesac\n",
		"ps": fmt.Sprintf("#!/bin/sh\n%sprintf '%%s\\n' '%d 700 /code/bin/grok' '700 1 bash'\n", meanwhile, os.Getppid()),
	} {
		write(t, filepath.Join(bin, name), script)
		if err := os.Chmod(filepath.Join(bin, name), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	if prepare != nil {
		prepare(state)
	}
	prompt := []byte(`{"hook_event_name": "UserPromptSubmit", "session_id": "new-session", "cwd": "/code/acme", "prompt": "Please go on."}`)
	var out bytes.Buffer
	if code = seatState(prompt, &out); out.Len() != 0 {
		t.Fatalf("%s: said %q", name, out.String())
	}
	return code, state
}

// A prompt the seat's own Grok ran in another session moves the seat there once the prompt's turn
// is latched: a latch that fails moves nothing.
func TestAGrokPromptMovesTheSeatOnceItsTurnIsLatched(t *testing.T) {
	for _, each := range []struct {
		name         string
		blocked      bool
		conversation string
	}{
		{"latched", false, "new-session"},
		{"the latch fails", true, "old-session"},
	} {
		code, state := grokPrompt(t, each.name, "", "", func(state string) {
			if each.blocked { // the latch's own temporary file cannot be written
				if err := os.Mkdir(filepath.Join(state, fmt.Sprintf("stop-acme.json.tmp.%d", os.Getpid())), 0o700); err != nil {
					t.Fatal(err)
				}
			}
		})
		moved, _ := run.ReadJSON(filepath.Join(state, "session-acme.json"))
		if code != 0 || moved.Str("conversation") != each.conversation {
			t.Fatalf("%s: exit %d, %s", each.name, code, run.Line(moved))
		}
	}
}

// A claim Go hands over leaves the prompt's turn as it was latched, for Python to latch: one on
// the person's own tmux server, from before ak had its own, and one whose record a writer holding
// its lock changed, while the claim read the process table, to one Go cannot write again.
func TestAFollowLeftToPythonFindsTheTurnUnlatched(t *testing.T) {
	const changed = `{"orchestrator": "nova", "conversation": "old-session", "id_source": "launcher", "cwd": "/code/acme", "session_title": "\ud800"}`
	for _, each := range []struct {
		name, server, meanwhile, record string
	}{
		{"on the person's own server", "case \"$1\" in -L) exit 1 ;; esac\n", "", grokRecord},
		{"changed meanwhile", "", "flock \"$HOME/.agentkit/state/.session-acme.lock\" mv \"$HOME/changed.json\" \"$HOME/.agentkit/state/session-acme.json\" 2>/dev/null\n", changed},
	} {
		code, state := grokPrompt(t, each.name, each.server, each.meanwhile, func(state string) {
			write(t, filepath.Join(filepath.Dir(filepath.Dir(state)), "changed.json"), changed)
		})
		kept, _ := os.ReadFile(filepath.Join(state, "session-acme.json"))
		latched, _ := os.ReadFile(filepath.Join(state, "stop-acme.json"))
		if code != 3 || string(kept) != each.record || string(latched) != grokLatch {
			t.Fatalf("%s: exit %d, left %s and %s", each.name, code, kept, latched)
		}
	}
}

// A follow Go hands over writes nothing first, not even the session an OpenCode seat's receipt
// says it is in, which the claim learns before it moves the seat: here one on the person's own
// tmux server, from before ak had its own.
func TestAnOpenCodeFollowLeftToPythonLearnsNothing(t *testing.T) {
	const record = `{"orchestrator": "mimo", "conversation": null, "cwd": "/code/acme", "opencode_launch": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}`
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.mimo]\nharness='opencode'\nmodel='mimo-1'\neffort='low'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	write(t, filepath.Join(state, "session-acme.json"), record)
	write(t, filepath.Join(state, "stop-acme.json"), grokLatch)
	write(t, filepath.Join(state, "opencode-launch-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "session"), "ses_AcmeOld")
	database := filepath.Join(home, "opencode.db")
	conn, err := sqlite.Open(database, sqlite3.OPEN_READWRITE|sqlite3.OPEN_CREATE)
	if err != nil {
		t.Fatal(err)
	}
	if err := conn.Exec("CREATE TABLE session_v2 (id TEXT, parent_id TEXT); INSERT INTO session_v2 VALUES ('ses_AcmeNew', NULL)"); err != nil {
		t.Fatal(err)
	}
	conn.Close()
	t.Setenv("OPENCODE_DB", database)
	t.Setenv("AGENTKIT_SESSION", "acme")
	t.Setenv("TMUX", "/tmp/acme-test,1,0")
	t.Setenv("TMUX_PANE", "%1")
	bin := t.TempDir()
	write(t, filepath.Join(bin, "tmux"), "#!/bin/sh\ncase \"$1\" in -L) exit 1 ;; esac\ncase \"$*\" in *list-sessions*) printf 'acme\\t1\\n' ;; *) exit 1 ;; esac\n")
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	code := seatState([]byte(`{"hook_event_name": "UserPromptSubmit", "session_id": "ses_AcmeNew", "prompt": "Build acme."}`), new(bytes.Buffer))
	kept, _ := os.ReadFile(filepath.Join(state, "session-acme.json"))
	latched, _ := os.ReadFile(filepath.Join(state, "stop-acme.json"))
	if code != 3 || string(kept) != record || string(latched) != grokLatch {
		t.Fatalf("exit %d, left %s and %s", code, kept, latched)
	}
}
