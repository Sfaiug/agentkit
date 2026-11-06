package seat

import (
	"os"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestABlankFrameKeepsTheLiveSeatsHookEvidence(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	write(t, stateFile(home, "plan-acme.md"), doneLine)
	drawn(t, home, "acme", "")
	for _, event := range []string{"", "UserPromptSubmit", "Stop"} {
		if event != "" {
			hookWrote(t, home, event, "")
		}
		lives, known := Lives(time.Now())
		if !known || len(lives) != 1 {
			t.Fatalf("a blank frame hid a live seat: known=%v, lives=%+v", known, lives)
		}
		want := "at_prompt"
		if event == "UserPromptSubmit" {
			want = "working"
		}
		if lives[0].State != want || lives[0].Draft != "" {
			t.Fatal(lives[0])
		}
	}
}

func TestABlankHealthFrameChangesOnlyWhatAHookDecides(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", "")
	path := stateFile(home, "seat-acme.json")
	before := `{"word":"needs you","state":"draft","unsent":"finish the patch"}`
	write(t, path, before)
	health := func() {
		t.Helper()
		if carried, err := Health("acme", func(Live) bool { return true }, func(string) {}, false); !carried || err != nil {
			t.Fatal(carried, err)
		}
	}
	health()
	if after, err := os.ReadFile(path); err != nil || string(after) != before {
		t.Fatalf("a blank frame changed its stored status: %s, %v", after, err)
	}
	hookWrote(t, home, "UserPromptSubmit", "")
	health()
	file, err := run.ReadJSON(path)
	if err != nil || file.Str("word") != "working" || file.Str("unsent") != "" {
		t.Fatal(file, err)
	}
}

func TestABlankHealthFrameStillPublishesItsGoingRun(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	write(t, stateFile(home, "plan-acme.md"), doneLine)
	runRecord(t, home, "r-build", map[string]any{"state": "running"})
	drawn(t, home, "acme", "")
	if carried, err := Health("acme", func(Live) bool { return true }, func(string) {}, false); !carried || err != nil {
		t.Fatal(carried, err)
	}
	if word, _ := Published("acme"); word != "working" {
		t.Fatal("a starting harness hid its going run:", word)
	}
}
