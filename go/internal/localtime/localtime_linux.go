package localtime

import (
	"cmp"
	"encoding/binary"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
)

// undated is a POSIX rule naming summer time but not its dates, such as `AKT5AKDT`: its names and
// offsets, the summer one left out for an hour on.
var undated = regexp.MustCompile(`^(<[A-Za-z0-9+-]{3,}>|[A-Za-z]{3,})([+-]?[0-9]+(?::[0-9]+){0,2})(<[A-Za-z0-9+-]{3,}>|[A-Za-z]{3,})([+-]?[0-9]+(?::[0-9]+){0,2})?,?$`)

// zone is the zone file glibc reads rule as.  An undated rule glibc dates by zoneinfo's posixrules
// (__tzfile_default), each change moved on: one given on the wall clock in summer time by the
// rule's summer offset, less the file's own, which glibc never reads, so 0 where TZ is read once;
// any other on the wall clock by the difference of the standard offsets, the file's being that of
// its last change to standard time.  After the last change the file's own footer holds, names and
// all.  Without a posixrules of two types glibc's dates are POSIX's, as Go's.
func zone(rule string) []byte {
	parts := undated.FindStringSubmatch(rule)
	if parts == nil {
		return posix(rule)
	}
	data, err := os.ReadFile(filepath.Join(cmp.Or(os.Getenv("TZDIR"), "/usr/share/zoneinfo"), "posixrules"))
	at, to, kinds, footer, read := zoneData(data)
	if err != nil || !read || len(kinds) < 2 {
		return posix(rule)
	}
	std, dst := east(parts[2]), east(parts[2])+3600
	if parts[4] != "" {
		dst = east(parts[4])
	}
	ruleStd := int32(0)
	for i := len(to) - 1; i >= 0; i-- {
		if !kinds[to[i]].summer {
			ruleStd = kinds[to[i]].offset
			break
		}
	}
	summer := false
	for i := range at {
		kind := kinds[to[i]]
		switch {
		case kind.ut:
		case summer && !kind.std:
			at[i] += int64(dst)
		default:
			at[i] += int64(std - ruleStd)
		}
		summer, to[i] = kind.summer, 0
		if summer {
			to[i] = 1
		}
	}
	if len(at) == 0 {
		footer = "" // a file that never changes is standard time throughout
	}
	return tzif(at, to, [2]int32{std, dst}, [2]string{strings.Trim(parts[1], "<>"), strings.Trim(parts[3], "<>")}, footer)
}

// east is a POSIX offset, hours west, as seconds east, each part capped as glibc caps it.
func east(offset string) int32 {
	sign, seconds := int32(-1), 0
	if offset[0] == '-' {
		sign = 1
	}
	for i, part := range strings.Split(strings.TrimLeft(offset, "+-"), ":") {
		n, _ := strconv.Atoi(part)
		seconds += min(n, []int{24, 59, 59}[i]) * []int{3600, 60, 1}[i]
	}
	return sign * int32(seconds)
}

// A kind is a zone file's type: its offset east, whether it is summer time, and whether its
// changes are given in standard time or in UTC rather than on the wall clock.
type kind struct {
	offset          int32
	summer, std, ut bool
}

// zoneData is a zone file's changes, the kind each is to, its kinds and its footer, from its
// 64-bit data where it has them, as glibc reads them; false where it does not read.
func zoneData(data []byte) (at []int64, to []byte, kinds []kind, footer string, read bool) {
	for size := 4; ; size = 8 {
		if len(data) < 44 || string(data[:4]) != "TZif" {
			return nil, nil, nil, "", false
		}
		var n [6]int // indicators of UTC and of standard time, leaps, changes, kinds, bytes of names
		for i := range n {
			n[i] = int(binary.BigEndian.Uint32(data[20+4*i:]))
		}
		body, length := data[44:], n[3]*(size+1)+n[4]*6+n[5]+n[2]*(size+4)+n[1]+n[0]
		if len(body) < length {
			return nil, nil, nil, "", false
		}
		if size == 4 && data[4] >= '2' {
			data = body[length:]
			continue
		}
		for i := range n[3] {
			if size == 4 {
				at = append(at, int64(int32(binary.BigEndian.Uint32(body[4*i:]))))
			} else {
				at = append(at, int64(binary.BigEndian.Uint64(body[8*i:])))
			}
		}
		to, body = slices.Clone(body[n[3]*size:n[3]*(size+1)]), body[n[3]*(size+1):]
		for i := range n[4] {
			kinds = append(kinds, kind{offset: int32(binary.BigEndian.Uint32(body[6*i:])), summer: body[6*i+4] != 0})
		}
		body = body[n[4]*6+n[5]+n[2]*(size+4):]
		for i := range min(n[1], len(kinds)) {
			kinds[i].std = body[i] != 0
		}
		for i := range min(n[0], len(kinds)) {
			kinds[i].ut = body[n[1]+i] != 0
		}
		if slices.ContainsFunc(to, func(each byte) bool { return int(each) >= len(kinds) }) {
			return nil, nil, nil, "", false
		}
		if rest := string(data[44+length:]); strings.HasPrefix(rest, "\n") {
			footer, _, _ = strings.Cut(rest[1:], "\n")
		}
		return at, to, kinds, footer, true
	}
}
