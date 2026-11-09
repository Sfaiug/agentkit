//go:build unix

package handback

import (
	"os"
	"path/filepath"
	"slices"
	"testing"

	"agentkit/internal/run"
)

// An ending whose seat nothing is left of asks the owner on that seat's card, as Python's
// orphan ending does; one whose seat keeps its record is Python's, left as it was.
func TestAnEndingOfASeatNothingIsLeftOfAsksTheOwner(t *testing.T) {
	for _, kept := range []bool{false, true} {
		home := t.TempDir()
		t.Setenv("HOME", home)
		t.Setenv("AGENTKIT_SESSION", "")
		t.Setenv("AK_RUN_ROLE", "")
		t.Setenv("AK_NOTIFY_SINK", "dry-run")
		bin, state := filepath.Join(home, "bin"), filepath.Join(home, ".agentkit", "state")
		dir := filepath.Join(home, ".agentkit", "runs", "20261020-0900-fix-api")
		for _, each := range []string{bin, state, dir} {
			if err := os.MkdirAll(each, 0o700); err != nil {
				t.Fatal(err)
			}
		}
		// no tmux server holds a session by that name
		os.WriteFile(filepath.Join(bin, "tmux"), []byte("#!/bin/sh\ncase \" $* \" in *has-session*) echo \"can't find session: omega\" >&2; exit 1;; esac\n"), 0o700)
		t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
		if kept {
			os.WriteFile(filepath.Join(state, "session-omega.json"), []byte(`{"orchestrator": "opus", "workers": ["opus"]}`), 0o600)
		}
		at := seconds() - 60
		ending := run.Fields("run_id", "20261020-0900-fix-api", "title", "fix-api", "state", "fail", "verdict", "FAIL",
			"launched_session", "omega", "repo", "/code/widgets", "started_at", run.Float(at-600), "finished_at", run.Float(at))
		if err := run.Create(dir, ending); err != nil {
			t.Fatal(err)
		}
		before, _ := run.Read(dir)
		var said []string
		if Give(dir, nil, func(line string) { said = append(said, line) }) {
			t.Fatal("the gone seat was told")
		}
		after, _ := run.Read(dir)
		notice, _ := run.ReadJSON(filepath.Join(state, "notify-omega.json"))
		if kept {
			if run.Line(after) != run.Line(before) || notice != nil {
				t.Errorf("a seat that keeps its record was not left to Python: %s, %v", run.Line(after), notice)
			}
			continue
		}
		line := "Its orchestrator session omega is gone. Run finished: FAIL. Press n in the menu, then say: continue fix-api."
		event := "orphan:20261020-0900-fix-api:" + run.Text(ending.Get("started_at")) + ":" + run.Text(ending.Get("finished_at"))
		card, _ := run.ReadJSON(filepath.Join(state, "card-omega.json"))
		switch {
		case !after.Truthy("reported") || after.Has("notification_pending") || after.Has("handback_pending"):
			t.Errorf("the ending was not reported: %s", run.Line(after))
		case notice == nil || notice.Str("text") != line || notice.Str("source") != event || notice.Get("watcher") != false:
			t.Errorf("the owner was asked %v", notice)
		case card == nil || card.Str("word") != "needs you" || !card.Truthy("sent"):
			t.Errorf("its card is %v", card)
		case !slices.Contains(said, "the orchestrator session omega this run was launched from is gone; asking the user to continue the task"):
			t.Errorf("said %q", said)
		}
	}
}
