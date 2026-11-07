//go:build unix

package tick

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestEndingsTellARunFromNoSeatNothingAndLeaveAQuestionGoCannotReadToPython(t *testing.T) {
	ak, _ := idleHome(t, answers)
	path := filepath.Join(ak, "runs", "review", "run.json")
	ended := run.Fields("state", "pass", "review_pr", "https://github.com/acme/widgets/pull/1", "finished_at", epoch(time.Now()))
	put(t, path, run.Line(ended))
	tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
	if err := tick.endings(); err != nil || read(t, path) != run.Line(ended) {
		t.Fatalf("a run from no seat was not carried as it stands: %v", err)
	}
	ended.Set("pending_inbox", []any{"Merge?"})
	put(t, path, run.Line(ended))
	if err := tick.endings(); !errors.Is(err, errLeft) || read(t, path) != run.Line(ended) {
		t.Fatalf("a merge question Go cannot read was not left to Python as it stands: %v", err)
	}
}

func TestEndingsLeaveToPythonWithNothingWrittenAMergeQuestionGoCannotTypeOrPing(t *testing.T) {
	ak, _ := idleHome(t, answers)
	t.Setenv("AGENTKIT_INBOX_SESSION", "acme")
	// an inbox on a harness Go knows nothing of, which it does not type into
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[models.vela]\nharness = 'acme'\nmodel = 'vela'\n"+
		"effort = 'high'\nprovider = 'test'\n[providers.test]\nmode = 'subscription'\n")
	put(t, filepath.Join(ak, "state", "session-acme.json"), `{"orchestrator": "vela", "workers": ["vela"], "conversation": "ses_A012z"}`)
	bin := t.TempDir()
	put(t, filepath.Join(bin, "tmux"), "#!/bin/sh\ncase \"$*\" in *list-sessions*) printf 'acme\\t1\\n' ;; *list-panes*) echo '%1 0' ;; "+
		"*send-keys*) touch \"$HOME/typed\" ;; esac\n")
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	path := filepath.Join(ak, "runs", "review", "run.json")
	tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
	for _, asked := range []bool{false, true} { // to type, then only to ping where no published word says the card is Go's
		ended := run.Fields("state", "pass", "review_pr", "https://github.com/acme/widgets/pull/7", "finished_at", epoch(time.Now()),
			"pending_inbox", run.Fields("question", "PR #7: Fix api. Merge? yes/no", "url", "https://github.com/acme/widgets/pull/7",
				"sha", "0123456789abcdef0123456789abcdef01234567", "asked", asked))
		put(t, path, run.Line(ended))
		if err := tick.endings(); !errors.Is(err, errLeft) || read(t, path) != run.Line(ended) {
			t.Fatalf("asked=%v: the merge question was not left to Python as it stands: %v", asked, err)
		}
		for _, written := range []string{filepath.Join(ak, "state", "notify-acme.json"), filepath.Join(filepath.Dir(ak), "typed")} {
			if _, err := os.Stat(written); !os.IsNotExist(err) {
				t.Fatalf("asked=%v: handed to Python after %s was written", asked, filepath.Base(written))
			}
		}
	}
}
