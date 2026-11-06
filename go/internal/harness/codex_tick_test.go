//go:build unix

package harness_test

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"agentkit/internal/browser"
	"agentkit/internal/run"
	"agentkit/internal/tick"
)

// the tick's browser tidy reads none: the host's shared browser is no test's
func init() { browser.CDP = "http://127.0.0.1:0" }

// TestATickBindsTheThreadACodexReceiptProves: Go's tick writes codex.py `reconcile` into each Codex
// seat's record, as Python's tick does, and goes on to its end.
func TestATickBindsTheThreadACodexReceiptProves(t *testing.T) {
	home, bin := t.TempDir(), t.TempDir()
	for key, value := range map[string]string{
		"HOME": home, "USERPROFILE": home, "TMUX_TMPDIR": t.TempDir(), "AGENTKIT_TMUX_SOCKET": "bind-test",
		"AGENTKIT_SESSION": "", "AGENTKIT_ADAPTER_DIR": "", "XDG_RUNTIME_DIR": t.TempDir(), "XDG_CONFIG_HOME": "",
		"AK_RUN_ROLE": "", "AK_NOTIFY_SINK": "dry-run", "PATH": bin + string(os.PathListSeparator) + os.Getenv("PATH"),
	} {
		t.Setenv(key, value)
	}
	put := func(path, text string) {
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil || os.WriteFile(path, []byte(text), 0o700) != nil {
			t.Fatal(path)
		}
	}
	// gh has nothing to act on, no tmux server holds a seat, and no collection is due
	put(filepath.Join(bin, "gh"), `#!/bin/sh
case "$*" in "api user") echo '{"login": "acme"}' ;; *) echo '{"items": []}' ;; esac
`)
	put(filepath.Join(bin, "tmux"), "#!/bin/sh\nexit 1\n")
	state := filepath.Join(home, ".agentkit", "state")
	put(filepath.Join(home, ".agentkit", "config.toml"), "[audit]\non=false\n[models.astra]\nharness='codex'\nmodel='gpt'\n"+
		"effort='high'\nprovider='openai'\n[providers.openai]\nmode='subscription'\n")
	put(filepath.Join(state, "gc.json"), fmt.Sprintf(`{"started_at": %d}`, time.Now().Unix()))
	cwd, rollout := filepath.Join(home, "acme"), filepath.Join(home, "rollout.jsonl")
	put(rollout, `{"type": "session_meta", "payload": {"id": "t1", "cwd": "`+cwd+`"}}`+"\n")
	proven, unproven := strings.Repeat("a", 32), strings.Repeat("b", 32)
	put(filepath.Join(state, "codex-launch-"+proven+".json"), `{"launch": "`+proven+`", "cwd": "`+cwd+`", "event": {"hook_event_name":
		"SessionStart", "source": "startup", "session_id": "t1", "cwd": "`+cwd+`", "transcript_path": "`+rollout+`"}}`)
	put(filepath.Join(state, "codex-launch-"+unproven+".json"), `{"launch": "`+unproven+`", "cwd": "`+cwd+`"}`)
	seat := func(name, launch string) string {
		path := filepath.Join(state, "session-"+name+".json")
		put(path, `{"orchestrator": "astra", "workers": ["astra"], "codex_launch": "`+launch+`", "conversation": "old",
			"id_source": "launcher", "resumable": true, "created": 1, "repo": null}`)
		return path
	}
	bound, kept := seat("acme", proven), seat("beta", unproven)
	if carried, failed := tick.Carry(io.Discard, io.Discard); !carried || failed {
		t.Fatalf("the tick handed over (carried %v, failed %v)", carried, failed)
	}
	for path, want := range map[string][]any{bound: {"t1", "codex-session-start", true}, kept: {"old", "launcher", false}} {
		record, _ := run.ReadJSON(path)
		if got := []any{record.Get("conversation"), record.Get("id_source"), record.Get("resumable")}; !reflect.DeepEqual(got, want) {
			t.Errorf("%s holds %v", filepath.Base(path), got)
		}
	}
}
