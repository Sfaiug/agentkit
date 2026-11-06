package seat

import (
	"os"
	"strconv"
	"strings"
	"testing"
	"time"
)

// A frame's look decides an untold ending from the runs its frame read, rereading none at rest:
// a home's history otherwise costs every refresh while a live seat is owed an ending.
func TestAnEndingIsDecidedFromItsFramesRuns(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", map[string]any{"repo": "", "filed": true})
	write(t, stateFile(home, "plan-acme.md"), "- [ ] Finish API\n")
	merged := runRecord(t, home, "merged", map[string]any{"state": "pass", "merged": true, "project": ""})
	history := runRecord(t, home, "history", map[string]any{"state": "pass", "merged": true, "handed_back": true, "project": "",
		"round_summaries": []any{map[string]any{"round": 1, "executor_summary": strings.Repeat("x", 3<<20)}}})
	week := time.Now().Add(-7 * 24 * time.Hour)
	for _, path := range []string{merged, history} {
		if err := os.Chtimes(path, week, week); err != nil {
			t.Fatal(err)
		}
	}
	drawn(t, home, "acme", prompting)
	frame, known := Menu(moment)
	if !known || len(frame.Seats) != 1 {
		t.Fatal("the menu does not read the live seat")
	}
	read := func() int {
		data, err := os.ReadFile("/proc/self/io")
		if err != nil {
			t.Fatal(err)
		}
		_, rest, _ := strings.Cut(string(data), "rchar: ")
		bytes, err := strconv.Atoi(strings.Fields(rest)[0])
		if err != nil {
			t.Fatal(err)
		}
		return bytes
	}
	before := read()
	if err := frame.Announce(moment); err != nil {
		t.Fatal(err)
	}
	if added := read() - before; added >= 3<<20 {
		t.Fatalf("the look read the runs again: %d bytes", added)
	}
}
