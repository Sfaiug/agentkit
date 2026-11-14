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
// is latched, and a latch that fails moves nothing.  The fake tmux keeps the latch as it stood
// when the claim asked which seats run.
func TestAGrokPromptMovesTheSeatOnceItsTurnIsLatched(t *testing.T) {
	for _, latched := range []bool{true, false} {
		home := sandbox(t)
		state := filepath.Join(home, ".agentkit", "state")
		write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.nova]\nharness='grokbuild'\nmodel='grok-test'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
		write(t, filepath.Join(state, "session-acme.json"), `{"orchestrator": "nova", "conversation": "old-session", "id_source": "launcher", "cwd": "/code/acme"}`)
		write(t, filepath.Join(state, "stop-acme.json"), `{"session": "acme", "turn": 1, "blocks": 2}`)
		t.Setenv("AGENTKIT_SESSION", "acme")
		t.Setenv("TMUX", "/tmp/acme-test,1,0")
		t.Setenv("TMUX_PANE", "%1")
		t.Setenv("GROK_HOME", "")
		bin := t.TempDir()
		t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
		for name, script := range map[string]string{
			"tmux": "#!/bin/sh\ncase \"$*\" in\n" +
				"*list-sessions*) cp \"$HOME/.agentkit/state/stop-acme.json\" \"$HOME/latched\"; printf 'acme\\t1\\n' ;;\n" +
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
		if !latched { // the latch's own temporary file cannot be written
			if err := os.Mkdir(filepath.Join(state, fmt.Sprintf("stop-acme.json.tmp.%d", os.Getpid())), 0o700); err != nil {
				t.Fatal(err)
			}
		}
		prompt := []byte(`{"hook_event_name": "UserPromptSubmit", "session_id": "new-session", "cwd": "/code/acme", "prompt": "Please go on."}`)
		if code := seatState(prompt, new(bytes.Buffer)); code != 0 {
			t.Fatalf("latched %v: exit %d", latched, code)
		}
		record, _ := run.ReadJSON(filepath.Join(state, "session-acme.json"))
		want := map[bool]string{true: "new-session", false: "old-session"}[latched]
		if record.Str("conversation") != want {
			t.Fatalf("latched %v: %s", latched, run.Line(record))
		}
		seen, _ := run.ReadJSON(filepath.Join(home, "latched"))
		if latched && seen.Get("blocks") != run.Number("0") {
			t.Fatalf("moved before its turn was latched: %v", seen)
		}
	}
}
