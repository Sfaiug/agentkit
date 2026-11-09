package suitetimes

import (
	"fmt"
	"maps"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/gitcall"
)

// A Pass is what one passing command printed of its test files' seconds, by file, and how many
// pieces it ran in, Python's gate.run_done_when timings.
type Pass struct {
	Times  map[string]float64
	Pieces int
}

// Refusal is the failure a change on checkout owes for each test file it adds since base that its
// suite's pass took longer over than the piece target, "" for none, Python's suite_times.refusal: a
// file slower than its piece slows every landing after it.  The suite base declares and a `tests:`
// line the change rewrites are each judged on their own pass alone, never on times kept from earlier
// ones, the target being that pass's seconds over its pieces, and at least 60, so many pieces never
// refuse an ordinary file of less than a minute.
func Refusal(checkout, base string, passes map[string]Pass) (string, error) {
	var added []string
	var failures []string
	for _, command := range slices.Compact([]string{gitcall.Suite(checkout, base), gitcall.Declared(checkout, "tests")}) {
		pass := passes[command]
		if len(pass.Times) == 0 {
			continue
		}
		if added == nil {
			names, err := gitcall.Git{Repo: checkout}.Must("diff", "--diff-filter=A", "--name-only", "-z", base+"...HEAD")
			if err != nil {
				return "", err
			}
			added = strings.Split(names, "\x00")
		}
		files := slices.Sorted(maps.Keys(pass.Times))
		total := 0.0
		for _, file := range files {
			total += pass.Times[file]
		}
		target := max(60, total/float64(pass.Pieces))
		var slow []string
		for _, file := range files {
			if seconds := pass.Times[file]; seconds > target && slices.Contains(added, file) {
				slow = append(slow, fmt.Sprintf("FAIL  %s: %ss exceeds the piece target %ss; split the test file.", file, said(seconds), said(target)))
			}
		}
		if len(slow) > 0 {
			failures = append(failures, "$ "+command+"\n[test file over piece target]\n"+strings.Join(slow, "\n"))
		}
	}
	return strings.Join(failures, "\n\n"), nil
}

// said is seconds as Python's `:g` writes them.
func said(seconds float64) string {
	return strconv.FormatFloat(seconds, 'g', 6, 64)
}
