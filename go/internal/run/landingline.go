package run

import (
	"cmp"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
)

// LineMembers is Python's land.line, which its lander and every reader of a place share: those of
// the runs, as their reader read them, holding a place in the line by that name, green deliveries
// in tested stack order, then join order.
func LineMembers(name string, runs []Held) []Held {
	var members []Held
	for _, each := range runs {
		if Member(each.Record) && each.Record.Dict("waiting_on").Str("line") == name {
			members = append(members, each)
		}
	}
	deliveries := map[string]string{}
	for _, m := range members {
		if wait := m.Record.Dict("waiting_on"); green(wait) {
			deliveries[m.Name] = wait.Str("land")
		}
	}
	depth := func(wait *Object) int {
		n := 0
		after := cmp.Or(wait.Dict("after"), NewObject())
		for _, name := range after.Keys() {
			if tree, ok := deliveries[name]; ok && tree == after.Str(name) {
				n++
			}
		}
		return n
	}
	slices.SortFunc(members, func(a, b Held) int {
		aw, bw := a.Record.Dict("waiting_on"), b.Record.Dict("waiting_on")
		if green(aw) != green(bw) {
			if green(aw) {
				return -1
			}
			return 1
		}
		if green(aw) {
			if order := cmp.Compare(depth(aw), depth(bw)); order != 0 {
				return order
			}
		}
		aj, _ := aw.Num("joined")
		bj, _ := bw.Num("joined")
		return cmp.Or(cmp.Compare(aj, bj), strings.Compare(a.Name, b.Name))
	})
	return members
}

// Standing is every run with a readable record as it stands, by its directory's name: the runs a
// reader holding none places a line's members among.
func Standing() []Held {
	var runs []Held
	for _, dir := range Dirs() {
		if record, _ := Read(dir); record != nil {
			runs = append(runs, Held{Name: filepath.Base(dir), Record: record})
		}
	}
	return runs
}

// green is whether a member's wait is a green delivery (land.green_delivery), which only needs
// delivering before its target moves.
func green(wait *Object) bool { return wait.Has("land") && !wait.Has("fix") }

// LandingLine is the line a waiting run waits in, "" for none (transitions.landing_line).
func LandingLine(record *Object) string {
	if wait := record.Dict("waiting_on"); wait != nil && record.Str("state") == "waiting" {
		return wait.Str("line")
	}
	return ""
}

// LinePlaces is the line under a run waiting in its landing line (status.parked_line), among the
// runs of one read, each line's members found once: where it stands there by its directory's name,
// and what it lands on, "" for one in no line; and whether that place is landing.line's: not in a
// line holding a member that is no green delivery while a seat was told its next run goes first
// (FirstPlaceTold), as landing.line orders such a fix.
func LinePlaces(runs []Held) func(record *Object, name string) (string, bool) {
	type order struct {
		names []string // first in line first
		read  bool
	}
	lines := map[string]order{}
	return func(record *Object, name string) (string, bool) {
		line := LandingLine(record)
		if line == "" {
			return "", true
		}
		found, seen := lines[line]
		if !seen {
			members := LineMembers(line, runs)
			found.read = !FirstPlaceTold() || !slices.ContainsFunc(members, func(m Held) bool {
				return !green(m.Record.Dict("waiting_on"))
			})
			for _, m := range members {
				found.names = append(found.names, m.Name)
			}
			lines[line] = found
		}
		place := 1 + slices.Index(found.names, name)
		if place == 0 {
			place = len(found.names) + 1
		}
		suffix := map[int]string{1: "st", 2: "nd", 3: "rd"}[place%10]
		if suffix == "" || 10 <= place%100 && place%100 <= 20 {
			suffix = "th"
		}
		target := strings.TrimPrefix(firstText(record, "main", "target", "base"), "origin/")
		return fmt.Sprintf("waiting · %d%s in line to land on %s", place, suffix, target), found.read
	}
}

// FirstPlaceTold is whether a check of tests/live.sh told a seat of its red that holds the
// install, whose next run then goes first in line as its fix (Python's update.first_place, read
// from the install's git, which Go leaves to Python); a hand-back Go cannot read may have told one.
func FirstPlaceTold() bool {
	// listed, not globbed: a HOME may hold a pattern's characters
	checks := filepath.Join(config.Home(), "state", "live-checks")
	entries, _ := os.ReadDir(checks)
	return slices.ContainsFunc(entries, func(check os.DirEntry) bool {
		record, err := ReadJSON(filepath.Join(checks, check.Name(), "handed"))
		return strings.Contains(check.Name(), "-") && (record != nil && record.Has("seat") || errors.Is(err, ErrLoneSurrogate))
	})
}
