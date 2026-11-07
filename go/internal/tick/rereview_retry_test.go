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

func rereviewDecisionHome(t *testing.T, prState string) (string, string, *ticking) {
	t.Helper()
	ak, _ := idleHome(t, `case "$*" in *"pr view"*) echo '{"state":"`+prState+`","reviewDecision":"CHANGES_REQUESTED","number":7,"title":"Add retry file"}' ;; *) echo '{"items":[]}' ;; esac`)
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

func TestRereviewSuccessfulUnmarkedDecisionIsNotTypedAgain(t *testing.T) {
	for _, state := range []string{"OPEN", "CLOSED"} {
		t.Run(state, func(t *testing.T) {
			ak, home, tick := rereviewDecisionHome(t, state)
			address := "https://github.com/acme/widgets/pull/7"
			dir := filepath.Join(ak, "runs", "add-retry-file")
			put(t, filepath.Join(dir, "run.json"), run.Line(run.Fields("state", "pass", "foreign", true, "pr", address, "launched_session", "lead", "merge_note", "waiting for the maintainer")))
			put(t, filepath.Join(dir, "result.md"), "waiting for the maintainer\n")
			put(t, filepath.Join(dir, "delivery.lock"), "")
			if err := os.Chmod(filepath.Join(dir, "delivery.lock"), 0o400); err != nil {
				t.Fatal(err)
			}
			if !tick.outgoing("beta") {
				return // before this milestone, the case is Python's before any keys
			}
			first := read(t, filepath.Join(home, "keys"))
			if strings.Count(first, "Nothing was posted to Discord") != 1 || strings.Count(first, "Enter\n") != 1 {
				t.Fatalf("fixture did not confirm one successful send: %s", first)
			}
			if err := os.Chmod(filepath.Join(dir, "delivery.lock"), 0o600); err != nil {
				t.Fatal(err)
			}
			for range 2 {
				if !tick.outgoing("beta") {
					t.Fatal("a successfully sent decision was handed over on retry")
				}
			}
			after := read(t, filepath.Join(home, "keys"))
			if after != first {
				t.Fatalf("decision was already confirmed sent, but after the receipt write recovered it was typed again: %s", after)
			}
			own := tick.state.Dict("own").Dict(address)
			if state == "OPEN" && own.Get("decision") != "CHANGES_REQUESTED" || state == "CLOSED" && !own.Truthy("done") {
				t.Fatal("successfully sent decision was not settled in own")
			}
		})
	}
}

