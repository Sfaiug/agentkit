package localtime

import (
	"testing"
	"time"
)

func TestRuleReadsAsTheCLibraryReadsIt(t *testing.T) {
	for _, each := range []struct {
		rule, name string
		at         time.Time
		offset     int
	}{
		{"AKT-5", "AKT", time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC), 5 * 3600},
		{"<+0530>-5:30", "+0530", time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC), 5*3600 + 1800},
		{"CET-1CEST,M3.5.0,M10.5.0/3", "CET", time.Date(2026, 1, 15, 12, 0, 0, 0, time.UTC), 3600},
		{"CET-1CEST,M3.5.0,M10.5.0/3", "CEST", time.Date(2026, 7, 15, 12, 0, 0, 0, time.UTC), 7200},
		{"EST5EDT", "EDT", time.Date(2026, 7, 15, 12, 0, 0, 0, time.UTC), -4 * 3600},
		{"nonsense", "UTC", time.Date(2026, 7, 15, 12, 0, 0, 0, time.UTC), 0},
		{"", "UTC", time.Date(2026, 7, 15, 12, 0, 0, 0, time.UTC), 0},
	} {
		local, err := time.LoadLocationFromTZData(each.rule, zone(each.rule))
		if err != nil {
			t.Fatalf("%q: %v", each.rule, err)
		}
		if name, offset := each.at.In(local).Zone(); name != each.name || offset != each.offset {
			t.Errorf("%q at %s: %s %d, want %s %d", each.rule, each.at, name, offset, each.name, each.offset)
		}
	}
}

func TestReadReplacesOnlyGosFallbackToUTC(t *testing.T) {
	read := time.FixedZone("Europe/Acme", 3600)
	for _, each := range []struct {
		before *time.Location
		offset int
	}{{time.UTC, -3 * 3600}, {read, 3600}} {
		saved := time.Local
		time.Local = each.before
		t.Setenv("TZ", ":ACT3")
		Read()
		_, offset := time.Now().Zone()
		time.Local = saved
		if offset != each.offset {
			t.Errorf("Go's own %s: offset %d, want %d", each.before, offset, each.offset)
		}
	}
}
