package usage

import (
	"slices"
	"testing"
)

// A refusal as Python keeps one is Go's to hand over, and a check's snapshot keeps the refusal it
// parks alone, every field of Python's usage.MARK the earlier ones held dropped.
func TestACheckSnapshotKeepsItsOwnRefusalAlone(t *testing.T) {
	held := fields("meters", []any{fields("name", "weekly_all", "used", 20)}, "exhausted_until", 1.0, "exhausted_at", 1.0,
		"exhausted_ends", fields(), "exhausted_used", fields(), "exhausted_by", "weekly_all",
		"exhausted_meters", []any{"weekly_all"}, "exhausted_earlier", []any{})
	if !Unread(held) || Unread(fields("exhausted_until", 1.0, "exhausted_by", "weekly_all")) || Unread(nil) {
		t.Error("only a refusal as Python keeps one is unread")
	}
	parked, until := Parked(held, "quota spent; try again at 2030-01-01T02:00:00Z")
	if keys := parked.Keys(); !slices.Equal(keys, []string{"meters", "exhausted_until"}) || until != 1893463200 {
		t.Errorf("parked holds %v until %v", keys, until)
	}
}
