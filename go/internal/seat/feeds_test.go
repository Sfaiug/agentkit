package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Only what a seat's word, row or card reads and Go does not carry hands a home over: a listed
// seat's own file Go does not read, but its done checks' counts and pictures; watch.json beside a
// stall Go does not read; and `server`.  The refusals rung 1a reads itself (runOnALogin).
func TestOnlyWhatFeedsASeatHandsTheHomeOver(t *testing.T) {
	state := filepath.Join(sandbox(t), ".agentkit", "state")
	for name, feeds := range map[string]bool{
		"plan-acme.md": false, "checked-acme.txt": false, "tell-acme.json": true, "verified-acme.txt": false, "unverified-acme.txt.new": false,
		"pictures-acme.jsonl": false, "plan-gone.md": false, "test-times-1a2b.json": false, "notices": false,
		"server": true, "leases/shop.json": false, "card-acme.json/held": true, "login-refusals.json": false,
	} {
		entry, _, _ := strings.Cut(name, "/") // a directory, where a name goes on past one
		write(t, filepath.Join(state, name), "{}")
		if feedsSeat(state, entry) != feeds {
			t.Errorf("%s feeds a seat: %v", name, !feeds)
		}
		os.RemoveAll(filepath.Join(state, entry))
	}
	for text, feeds := range map[string]bool{
		`{"seats_mb": 2310, "quiet": {}, "own": [], "stalls": {}}`: false, `{"stalls": {"acme": {"since": 1, "told": []}}}`: false,
		`{"stalls": {"acme": {"kind": "window"}}}`: true, `{"stalls": []}`: true, `[]`: true, `{`: true,
	} {
		write(t, filepath.Join(state, "watch.json"), text)
		if feedsSeat(state, "watch.json") != feeds {
			t.Errorf("watch.json %s feeds a seat: %v", text, !feeds)
		}
	}
}

// A seat file's write lands through its temporary path, which no word reads: whatever stands
// there, a directory too, the home still reads, and that write warns (watch.seat_write).
func TestASeatsTemporaryDirectoryPassesOver(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	if err := os.Mkdir(filepath.Join(home, ".agentkit", "state", "seat-acme.tmp"), 0o700); err != nil {
		t.Fatal(err)
	}
	if found, known := Read(moment); !known || len(found.Seats) != 1 {
		t.Fatalf("known=%v seats=%+v", known, found.Seats)
	}
}

// feedsSeat is feeds of the entry of that name, beside the listed seat acme.
func feedsSeat(state, name string) bool {
	entries, _ := os.ReadDir(state)
	for _, entry := range entries {
		if entry.Name() == name {
			return feeds(state, entry, []string{"acme"}, nil)
		}
	}
	return false
}
