package run

import (
	"cmp"
	"errors"
	"fmt"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
)

// A LineMember is a run holding a place in its landing line (Member), as read.
type LineMember struct {
	Dir    string
	Record *Object
}

// LineMembers is Python's land.line, which its lander and every reader of a place share: the runs
// holding a place in the line by that name, green deliveries in tested stack order, then join order.
func LineMembers(name string) []LineMember {
	var members []LineMember
	for _, dir := range Dirs() {
		if record, _ := Read(dir); record != nil && Member(record) && record.Dict("waiting_on").Str("line") == name {
			members = append(members, LineMember{dir, record})
		}
	}
	deliveries := map[string]string{}
	for _, m := range members {
		if wait := m.Record.Dict("waiting_on"); green(wait) {
			deliveries[filepath.Base(m.Dir)] = wait.Str("land")
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
	slices.SortFunc(members, func(a, b LineMember) int {
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
		return cmp.Or(cmp.Compare(aj, bj), strings.Compare(a.Dir, b.Dir))
	})
	return members
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

// LinePlace is the line under a run waiting in its landing line (status.parked_line): where it
// stands there by its directory's name, and what it lands on; "" for one in no line.
func LinePlace(record *Object, name string) string {
	place, _ := LinePlaces()(record, name)
	return place
}

// LinePlaces is LinePlace for the runs of one read, each line's members read once, and whether
// that place is landing.line's: not in a line holding a member that is no green delivery while a
// seat was told its next run goes first (FirstPlaceTold), as landing.line orders such a fix.
func LinePlaces() func(record *Object, name string) (string, bool) {
	type line struct {
		names []string
		read  bool
	}
	lines := map[string]line{}
	return func(record *Object, name string) (string, bool) {
		line := LandingLine(record)
		if line == "" {
			return "", true
		}
		found, seen := lines[line]
		if !seen {
			members := LineMembers(line)
			found.read = !FirstPlaceTold() || !slices.ContainsFunc(members, func(m LineMember) bool {
				return !green(m.Record.Dict("waiting_on"))
			})
			for _, m := range members {
				found.names = append(found.names, filepath.Base(m.Dir))
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
	told, _ := filepath.Glob(filepath.Join(config.Home(), "state", "live-checks", "*-*", "handed"))
	return slices.ContainsFunc(told, func(path string) bool {
		record, err := ReadJSON(path)
		return record != nil && record.Has("seat") || errors.Is(err, ErrLoneSurrogate)
	})
}
