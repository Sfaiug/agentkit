package cli

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A prompt the seat's own Grok ran in another session moves the seat there once the prompt's turn
// is latched: a latch that fails moves nothing, and a claim Go hands over writes neither, as for a
// seat on the person's own tmux server, from before ak had its own.
func TestAGrokPromptMovesTheSeatOnceItsTurnIsLatched(t *testing.T) {
	const record = `{"orchestrator": "nova", "conversation": "old-session", "id_source": "launcher", "cwd": "/code/acme"}`
	const latch = `{"session": "acme", "turn": 1, "blocks": 2}`
	for _, each := range []struct {
		name            string
		blocked, legacy bool
		code            int
		conversation    string
	}{
		{"latched", false, false, 0, "new-session"},
		{"the latch fails", true, false, 0, "old-session"},
		{"on the person's own server", false, true, 3, "old-session"},
	} {
		home := sandbox(t)
		state := filepath.Join(home, ".agentkit", "state")
		write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.nova]\nharness='grokbuild'\nmodel='grok-test'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
		write(t, filepath.Join(state, "session-acme.json"), record)
		write(t, filepath.Join(state, "stop-acme.json"), latch)
		t.Setenv("AGENTKIT_SESSION", "acme")
		t.Setenv("TMUX", "/tmp/acme-test,1,0")
		t.Setenv("TMUX_PANE", "%1")
		t.Setenv("GROK_HOME", "")
		bin := t.TempDir()
		t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
		own := ""
		if each.legacy { // ak's own server, asked for by -L, holds no seat
			own = "case \"$1\" in -L) exit 1 ;; esac\n"
		}
		for name, script := range map[string]string{
			"tmux": "#!/bin/sh\n" + own + "case \"$*\" in\n" +
				"*list-sessions*) printf 'acme\\t1\\n' ;;\n" +
				"*list-panes*) printf 'acme\\t0\\n' ;;\n" +
				"*display-message*socket_path*) printf '/tmp/acme-test\\tacme\\t700\\t%%1\\n' ;;\n" +
				"*) exit 1 ;;\nesac\n",
			"ps": fmt.Sprintf("#!/bin/sh\nprintf '%%s\\n' '%d 700 /code/bin/grok' '700 1 bash'\n", os.Getppid()),
		} {
			write(t, filepath.Join(bin, name), script)
			if err := os.Chmod(filepath.Join(bin, name), 0o700); err != nil {
				t.Fatal(err)
			}
		}
		if each.blocked { // the latch's own temporary file cannot be written
			if err := os.Mkdir(filepath.Join(state, fmt.Sprintf("stop-acme.json.tmp.%d", os.Getpid())), 0o700); err != nil {
				t.Fatal(err)
			}
		}
		prompt := []byte(`{"hook_event_name": "UserPromptSubmit", "session_id": "new-session", "cwd": "/code/acme", "prompt": "Please go on."}`)
		var out bytes.Buffer
		if code := seatState(prompt, &out); code != each.code || out.Len() != 0 {
			t.Fatalf("%s: exit %d, said %q", each.name, code, out.String())
		}
		kept, _ := os.ReadFile(filepath.Join(state, "session-acme.json"))
		if moved, _ := run.ReadJSON(filepath.Join(state, "session-acme.json")); moved.Str("conversation") != each.conversation {
			t.Fatalf("%s: %s", each.name, kept)
		}
		latched, _ := os.ReadFile(filepath.Join(state, "stop-acme.json"))
		if each.code == 3 && (string(kept) != record || string(latched) != latch) {
			t.Fatalf("%s: handed over having written %s and %s", each.name, kept, latched)
		}
	}
}
