package seat

import (
	"fmt"
	"regexp"
	"slices"
	"strings"
)

// lineEnd is where Python's str.splitlines ends a line.
var lineEnd = regexp.MustCompile("\r\n|[\n\r\v\f\x1c\x1d\x1e\u0085  ]")

// keepLines is text's lines each with its end, as Python's str.splitlines(True).
func keepLines(text string) []string {
	var lines []string
	from := 0
	for _, end := range lineEnd.FindAllStringIndex(text, -1) {
		lines = append(lines, text[from:end[1]])
		from = end[1]
	}
	if from < len(text) {
		lines = append(lines, text[from:])
	}
	return lines
}

// unifiedDiff is Python's difflib.unified_diff of those lines at that much context, hunk for hunk,
// so a seat is told the same diff by either build.
func unifiedDiff(a, b []string, fromName, toName string, context int) string {
	var out strings.Builder
	for _, group := range groupedOpcodes(opcodes(a, b), context) {
		if out.Len() == 0 {
			fmt.Fprintf(&out, "--- %s\n+++ %s\n", fromName, toName)
		}
		first, last := group[0], group[len(group)-1]
		fmt.Fprintf(&out, "@@ -%s +%s @@\n", hunkRange(first.i1, last.i2), hunkRange(first.j1, last.j2))
		for _, code := range group {
			if code.tag == ' ' {
				writeLines(&out, " ", a[code.i1:code.i2])
				continue
			}
			writeLines(&out, "-", a[code.i1:code.i2])
			writeLines(&out, "+", b[code.j1:code.j2])
		}
	}
	return out.String()
}

func writeLines(out *strings.Builder, mark string, lines []string) {
	for _, line := range lines {
		out.WriteString(mark + line)
	}
}

// hunkRange is difflib's _format_range_unified.
func hunkRange(start, stop int) string {
	switch length := stop - start; length {
	case 1:
		return fmt.Sprint(start + 1)
	case 0:
		return fmt.Sprintf("%d,0", start)
	default:
		return fmt.Sprintf("%d,%d", start+1, length)
	}
}

// An opcode turns a[i1:i2] into b[j1:j2]: ' ' where they are equal.
type opcode struct {
	tag            byte
	i1, i2, j1, j2 int
}

// opcodes is SequenceMatcher(None, a, b).get_opcodes, with no tag but equal and not.
func opcodes(a, b []string) []opcode {
	var codes []opcode
	i, j := 0, 0
	for _, block := range matchingBlocks(a, b) {
		if i < block[0] || j < block[1] {
			codes = append(codes, opcode{'!', i, block[0], j, block[1]})
		}
		i, j = block[0]+block[2], block[1]+block[2]
		if block[2] > 0 {
			codes = append(codes, opcode{' ', block[0], i, block[1], j})
		}
	}
	return codes
}

// groupedOpcodes is get_grouped_opcodes: each hunk, with that much context around its changes.
func groupedOpcodes(codes []opcode, n int) [][]opcode {
	if len(codes) == 0 {
		codes = []opcode{{' ', 0, 1, 0, 1}}
	}
	if head := &codes[0]; head.tag == ' ' {
		head.i1, head.j1 = max(head.i1, head.i2-n), max(head.j1, head.j2-n)
	}
	if tail := &codes[len(codes)-1]; tail.tag == ' ' {
		tail.i2, tail.j2 = min(tail.i2, tail.i1+n), min(tail.j2, tail.j1+n)
	}
	var groups [][]opcode
	var group []opcode
	for _, code := range codes {
		if code.tag == ' ' && code.i2-code.i1 > n+n {
			group = append(group, opcode{' ', code.i1, min(code.i2, code.i1+n), code.j1, min(code.j2, code.j1+n)})
			groups = append(groups, group)
			group = nil
			code.i1, code.j1 = max(code.i1, code.i2-n), max(code.j1, code.j2-n)
		}
		group = append(group, code)
	}
	if len(group) > 0 && !(len(group) == 1 && group[0].tag == ' ') {
		groups = append(groups, group)
	}
	return groups
}

// matchingBlocks is get_matching_blocks with difflib's autojunk: each {i, j, size} in order,
// adjacent ones merged, ending on the empty one at both ends.  In a b of at least 200 lines, a
// line making up more than 1% of it starts no match.
func matchingBlocks(a, b []string) [][3]int {
	where := map[string][]int{}
	for at, line := range b {
		where[line] = append(where[line], at)
	}
	if len(b) >= 200 {
		for line, at := range where {
			if len(at) > len(b)/100+1 {
				delete(where, line)
			}
		}
	}
	var blocks [][3]int
	queue := [][4]int{{0, len(a), 0, len(b)}}
	for len(queue) > 0 {
		span := queue[len(queue)-1]
		queue = queue[:len(queue)-1]
		i, j, size := longestMatch(a, b, where, span)
		if size == 0 {
			continue
		}
		blocks = append(blocks, [3]int{i, j, size})
		if span[0] < i && span[2] < j {
			queue = append(queue, [4]int{span[0], i, span[2], j})
		}
		if i+size < span[1] && j+size < span[3] {
			queue = append(queue, [4]int{i + size, span[1], j + size, span[3]})
		}
	}
	slices.SortFunc(blocks, func(x, y [3]int) int { return slices.Compare(x[:], y[:]) })
	var merged [][3]int
	for _, block := range blocks {
		if end := len(merged) - 1; end >= 0 && merged[end][0]+merged[end][2] == block[0] && merged[end][1]+merged[end][2] == block[1] {
			merged[end][2] += block[2]
		} else {
			merged = append(merged, block)
		}
	}
	return append(merged, [3]int{len(a), len(b), 0})
}

// longestMatch is find_longest_match over {alo, ahi, blo, bhi}: the earliest of the longest, grown
// over what autojunk left out.
func longestMatch(a, b []string, where map[string][]int, span [4]int) (besti, bestj, best int) {
	besti, bestj = span[0], span[2]
	lengths := map[int]int{}
	for i := span[0]; i < span[1]; i++ {
		next := map[int]int{}
		for _, j := range where[a[i]] {
			if j < span[2] {
				continue
			}
			if j >= span[3] {
				break
			}
			k := lengths[j-1] + 1
			next[j] = k
			if k > best {
				besti, bestj, best = i-k+1, j-k+1, k
			}
		}
		lengths = next
	}
	for besti > span[0] && bestj > span[2] && a[besti-1] == b[bestj-1] {
		besti, bestj, best = besti-1, bestj-1, best+1
	}
	for besti+best < span[1] && bestj+best < span[3] && a[besti+best] == b[bestj+best] {
		best++
	}
	return besti, bestj, best
}
