//go:build unix

package tick

import (
	"errors"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A title send already on a seat's record is Python's to retry, whatever its harness: the look
// takes a send on the record for this pass's own, and Go types no title into a Grok seat.
func TestAnEarlierTitleSendIsLeftToPythonWhateverTheHarness(t *testing.T) {
	ak, _ := idleHome(t, answers)
	t.Setenv("GROK_HOME", "")
	put(t, filepath.Join(ak, "config.toml"), "[models.nova]\nharness='grokbuild'\nmodel='grok-test'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	conversation := "01234567-89ab-cdef-0123-456789abcdef"
	cwd := filepath.Join(filepath.Dir(ak), "work", "acme")
	put(t, filepath.Join(filepath.Dir(ak), ".grok", "sessions", strings.ReplaceAll(url.QueryEscape(cwd), "+", "%20"), conversation, "summary.json"), run.Line(run.Fields(
		"info", run.Fields("id", conversation, "cwd", cwd), "title_is_manual", false, "generated_title", "Build the report", "current_model_id", "grok-test", "reasoning_effort", "high")))
	put(t, filepath.Join(ak, "state", "session-acme.json"), run.Line(run.Fields("orchestrator", "nova", "workers", []any{"nova"}, "created", 1,
		"cwd", cwd, "conversation", conversation, "id_source", "launcher", "resumable", true,
		"session_title", nil, "title_conversation", conversation, "title_sync", run.Fields("name", "acme", "tries", 1, "pending", false))))
	put(t, filepath.Join(ak, "state", "usage.json"), run.Line(run.Fields("fetched_at", epoch(time.Now()), "providers", run.Fields("test", run.Fields("meters", []any{})))))
	screen, err := os.ReadFile("../../../tests/fixtures/grok-prompt-pane.txt")
	if err != nil {
		t.Fatal(err)
	}
	put(t, filepath.Join(filepath.Dir(ak), "screen"), string(screen))
	bin := strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0]
	put(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in '-L tick-test '*) ;; *) exit 1 ;; esac
case "$*" in
  *list-sessions*) printf 'acme\t1\n' ;;
  *'#{pane_id} #{pane_dead}'*) printf '0 1 %%1 0\n' ;;
  *list-panes*) printf 'acme\t0\n' ;;
  *capture-pane*display-message*) cat "$HOME/screen"; printf '\n0\n' ;;
  *capture-pane*) cat "$HOME/screen" ;;
  *session_attached*) printf '0\t%%1\t%s\n' "$HOME" ;;
  *show-options*) echo %1 ;;
  *display-message*) echo acme ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := checking(t, io.Discard).health(); !errors.Is(err, errLeft) {
		t.Fatalf("an earlier send of the title was taken for this pass's own: %v", err)
	}
}
