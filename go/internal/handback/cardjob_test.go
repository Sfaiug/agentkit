//go:build unix

package handback

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/job"
	"agentkit/internal/run"
)

// A finished job whose seat nothing is left of asks the owner on that seat's card with the job's
// own text, once for its ending, and its line is struck off the receipt, carded.
func TestAJobsLineForAGoneSeatCardsTheOwner(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("AGENTKIT_SESSION", "")
	t.Setenv("AK_RUN_ROLE", "")
	t.Setenv("AK_NOTIFY_SINK", "dry-run")
	bin, state := filepath.Join(home, "bin"), filepath.Join(home, ".agentkit", "state")
	dir := filepath.Join(home, ".agentkit", "jobs", "20261108-090000-fix-api")
	for _, each := range []string{bin, state, dir} {
		if err := os.MkdirAll(each, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	// no tmux server holds a session by that name
	os.WriteFile(filepath.Join(bin, "tmux"), []byte("#!/bin/sh\ncase \" $* \" in *has-session*) echo \"can't find session: omega\" >&2; exit 1;; esac\n"), 0o700)
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	text := "job 20261108-090000-fix-api: all 2 tasks finished"
	receipt := run.Fields("job_id", "20261108-090000-fix-api", "seat", "omega", "finished_at", run.Float(seconds()),
		"handback_pending", text+". Result: "+filepath.Join(dir, "log.txt")+". Decide the next step.", "handback_card", text)
	if err := job.Save(dir, receipt); err != nil {
		t.Fatal(err)
	}
	if !CardJob(dir, receipt, func(string) {}) {
		t.Fatal("the card was not accepted")
	}
	after, _ := job.Read(dir)
	notice, _ := run.ReadJSON(filepath.Join(state, "notify-omega.json"))
	card, _ := run.ReadJSON(filepath.Join(state, "card-omega.json"))
	switch event := "job:20261108-090000-fix-api:" + run.Text(receipt.Get("finished_at")); {
	case after.Dict("card_sent").Str("kind") != "needs" || after.Has("handback_pending") || after.Has("handback_card"):
		t.Errorf("the receipt: %s", run.Line(after))
	case notice == nil || notice.Str("text") != text || notice.Str("source") != event:
		t.Errorf("the owner was asked %v", notice)
	case card == nil || card.Str("word") != "needs you" || !card.Truthy("sent"):
		t.Errorf("its card is %v", card)
	}
}
