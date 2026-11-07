package run

import (
	"cmp"
	"fmt"
	"path/filepath"
	"slices"
	"strings"
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
	green := func(wait *Object) bool { return wait.Has("land") && !wait.Has("fix") }
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

// LinePlace is the line under a run waiting in its landing line (status.parked_line): where it
// stands there by its directory's name, and what it lands on; "" for one in no line.
func LinePlace(record *Object, name string) string {
	wait := record.Dict("waiting_on")
	if record.Str("state") != "waiting" || wait == nil || wait.Str("line") == "" {
		return ""
	}
	members := LineMembers(wait.Str("line"))
	place := 1 + slices.IndexFunc(members, func(m LineMember) bool { return filepath.Base(m.Dir) == name })
	if place == 0 {
		place = len(members) + 1
	}
	suffix := map[int]string{1: "st", 2: "nd", 3: "rd"}[place%10]
	if suffix == "" || 10 <= place%100 && place%100 <= 20 {
		suffix = "th"
	}
	target := strings.TrimPrefix(firstText(record, "main", "target", "base"), "origin/")
	return fmt.Sprintf("waiting · %d%s in line to land on %s", place, suffix, target)
}
