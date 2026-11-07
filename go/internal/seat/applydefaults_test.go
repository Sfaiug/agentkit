//go:build unix

package seat

import (
	"testing"

	"agentkit/internal/run"
)

func TestApplyLeavesReviewersTheDefaultsDoNotNameToFollowTheExecutors(t *testing.T) {
	home := sandbox(t)
	write(t, stateFile(home, "../config.toml"), testConfig+"[defaults]\norchestrator='fable'\nworkers=['opus']\n")
	record(t, home, "acme", map[string]any{"orchestrator": "fable", "workers": []string{"fable"}, "reviewers": []string{"fable"}})
	given, known := DefaultsMove([]string{"acme"}, "fable")
	if !known {
		t.Fatal("Go cannot tell what `a` changes")
	}
	if said, known := given.Apply(); !known || said != "" {
		t.Fatal(said, known)
	}
	after, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
	if run.Line(after.Get("workers")) != `["opus"]` || after.Has("reviewers") {
		t.Fatal("the record did not take the defaults", run.Line(after))
	}
	if _, err := ConfigSelection("acme"); err != nil {
		t.Fatal("Apply left a record no seat reads:", err)
	}
}
