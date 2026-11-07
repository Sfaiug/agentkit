//go:build unix

package tick

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
	"agentkit/internal/run"
)

// A harness supported by TypeAtPrompt, with all tmux calls confined to a fake.
func reviewDecisionHome(t *testing.T, script string) (string, string, *ticking) {
	t.Helper()
	ak, _ := idleHome(t, script)
	home := filepath.Dir(ak)
	bin := t.TempDir()
	put(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *list-sessions*session_created*) printf 'lead\t1\t1000\n' ;;
  *list-sessions*) printf 'lead\t1\n' ;;
  *list-panes*) echo '%1 0' ;;
  *capture-pane*) cat "$HOME/shown" ;;
  *display-message*'#{pane_id}'*) printf '%%1\t1000\n' ;;
  *send-keys*)
    for last do :; done
    printf '%s\n' "$last" >> "$HOME/keys"
    if [ "$last" = Enter ]; then
      [ ! -e "$HOME/reject-enter" ] || exit 1
      printf '────────\n❯\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n' > "$HOME/shown"
    else
      printf '────────\n❯ %s\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n' "$last" > "$HOME/shown"
    fi ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non=false\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	put(t, filepath.Join(ak, "state", "session-lead.json"), run.Line(run.Fields("orchestrator", "opus", "workers", []any{"opus"}, "conversation", "conv-lead", "cwd", home)))
	put(t, filepath.Join(home, "shown"), "────────\n❯\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n")
	state, _ := loadState()
	return ak, home, &ticking{state: state, log: newLog(io.Discard, io.Discard), clock: time.Now}
}

func TestReviewUnsupportedDecisionLeavesOwnUntouched(t *testing.T) {
	ak, _, tick := reviewDecisionHome(t, `case "$*" in *"pr view"*) echo '{"state":"OPEN","reviewDecision":"CHANGES_REQUESTED","number":7,"title":"Add retry file"}' ;; *) echo '{"items":[]}' ;; esac`)
	path := filepath.Join(ak, "config.toml")
	put(t, path, strings.ReplaceAll(read(t, path), "harness='claude'", "harness='antigravity'"))
	dir := filepath.Join(ak, "runs", "add-retry-file")
	put(t, filepath.Join(dir, "run.json"), `{"state":"pass","foreign":true,"pr":"https://github.com/acme/widgets/pull/7","launched_session":"lead","merge_note":"waiting for the maintainer"}`)
	before := run.Line(tick.state)
	if tick.outgoing("beta") {
		t.Fatal("unsupported harness was carried")
	}
	// Carry saves the state even when github/outgoing hands the remainder to Python.
	if err := tick.save(); err != nil {
		t.Fatal(err)
	}
	if run.Line(tick.state) != before {
		t.Fatalf("unsupported decision was saved into watch.json before fallback: %s", read(t, filepath.Join(ak, "state", "watch.json")))
	}
}
