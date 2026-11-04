package seat

import (
	"bytes"
	"os"
	"testing"

	"agentkit/internal/run"
)

func TestAnInteractiveOpenWritesOnlyItsBaselineAndGeneration(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	path := stateFile(home, "session-acme.json")
	before, _ := os.ReadFile(path)
	write(t, stateFile(home, "watch.json"), `{"stalls":{"acme":{"at":1},"other":{"at":2}},"seen_at":{"acme":9000000000,"other":4}}`)
	write(t, seatFile("acme"), `{"word":"needs you","unasked":{"text":"Which date?"}}`)
	var errOut bytes.Buffer
	recordOpening("acme", &errOut)
	watch, _ := run.ReadJSON(stateFile(home, "watch.json"))
	stamp, _ := watch.Dict("seen_at").Num("acme")
	want := run.Fields("reviewed", run.NewObject(), "own", run.NewObject(), "after_merge", run.NewObject(),
		"stalls", run.Fields("other", run.Fields("at", 2)), "seen_at", run.Fields("acme", stamp, "other", 4))
	if errOut.Len() != 0 || stamp <= 9_000_000_000 || !run.Equal(watch, want) {
		t.Fatalf("watch %s, stderr %s", run.Encode(watch), &errOut)
	}
	seat, _ := run.ReadJSON(seatFile("acme"))
	opened, _ := seat.Num("opened_at")
	seat.Delete("opened_at")
	if opened <= 0 || !run.Equal(seat, run.Fields("session", "acme", "word", "needs you", "unasked", run.Fields("text", "Which date?"))) {
		t.Fatal(run.Encode(seat))
	}
	if after, _ := os.ReadFile(path); string(after) != string(before) {
		t.Fatal("opening changed the conversation record")
	}
}

func TestMenuLeavesReopeningAndNoticeBaselinesToPython(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	var out, errOut bytes.Buffer
	if known, err := Visit("acme", false, &out, &errOut); known || err != nil || out.Len()+errOut.Len() != 0 {
		t.Fatal("the menu reopened a gone seat", known, err)
	}
	if known, err := Visit("acme", true, &out, &errOut); !known || err != nil || out.String() != "would resume acme\n" {
		t.Fatal(known, err, out.String())
	}
	drawn(t, home, "acme", prompting)
	out.Reset()
	path := stateFile(home, "notify-acme.json")
	write(t, path, `{"kind":"needs","text":"Which date?","time":5}`)
	before, _ := os.ReadFile(path)
	if known, err := Visit("acme", false, &out, &errOut); known || err != nil || out.Len()+errOut.Len() != 0 {
		t.Fatal("the menu took a notice whose open needs Python", known, err)
	}
	if after, _ := os.ReadFile(path); string(after) != string(before) {
		t.Fatal("handing over changed the notice")
	}
	if _, err := os.Stat(seatFile("acme")); !os.IsNotExist(err) {
		t.Fatal("a dry run or handover recorded an interactive open")
	}
}
