package suitetimes

import (
	"cmp"
	"fmt"
	"maps"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/gitcall"
)

// A Pass is what one passing suite printed of its test files' seconds, by file, and how many
// pieces it ran in, Python's gate.run_done_when timings.
type Pass struct {
	Command string
	Times   map[string]float64
	Pieces  int
}

// A Version is files at the commit ref names, for a Timer.
type Version struct {
	Ref   string
	Files []string
}

// A Timer is, for each version, the seconds by file the suite command printed running just its
// files at its commit, together on this machine, Python's suite_times.timed: none for a version
// it could not time.
type Timer func(command string, versions ...Version) ([]map[string]float64, error)

// Refusal is the failure a change on checkout owes for each test file it adds since base that its
// suite's pass took longer over than the piece target, "" for none, Python's suite_times.refusal: a
// file slower than its piece slows every landing after it.  Each suite is judged on its own pass
// alone, never on times kept from earlier ones, the target being that pass's seconds over its
// pieces, and at least 60, so many pieces never refuse an ordinary file of less than a minute.  A
// file the change edits (a move or a new file type is an edit) owes it only where the change put
// it there: timed again at once on both versions, over the target at HEAD and at most it on base.
// Both versions on one machine at one moment leave host load and other changes' checks out; only
// both timings decide, so a version that timed nothing refuses nothing.  Refused is the first
// suite refused for: only a pass of that suite shows the file again.
func Refusal(checkout, base string, passes []Pass, timed Timer) (refused, failure string, err error) {
	var changed map[string]string
	var failures []string
	for _, pass := range passes {
		if len(pass.Times) == 0 {
			continue
		}
		if changed == nil {
			if changed, err = origins(checkout, base); err != nil {
				return "", "", err
			}
		}
		files := slices.Sorted(maps.Keys(pass.Times))
		total := 0.0
		for _, file := range files {
			total += pass.Times[file]
		}
		target := max(60, total/float64(pass.Pieces))
		var over, olds, edited []string
		for _, file := range files {
			if old, ok := changed[file]; ok && pass.Times[file] > target {
				over = append(over, file)
				if old != "" {
					olds, edited = append(olds, old), append(edited, file)
				}
			}
		}
		then, now := map[string]float64{}, map[string]float64{}
		if len(edited) > 0 {
			found, err := timed(pass.Command, Version{base, olds}, Version{"HEAD", edited})
			if err != nil {
				return "", "", err
			}
			then, now = found[0], found[1]
		}
		var slow []string
		for _, file := range over {
			took := said(pass.Times[file]) + "s"
			if old := changed[file]; old != "" {
				was, before := then[old]
				is, after := now[file]
				if !before || !after || was > target || is <= target {
					continue
				}
				took = fmt.Sprintf("%ss, up from %ss on %s,", said(is), said(was), base)
			}
			slow = append(slow, fmt.Sprintf("FAIL  %s: %s exceeds the piece target %ss; split the test file or make it faster.", file, took, said(target)))
		}
		if len(slow) > 0 {
			refused = cmp.Or(refused, pass.Command)
			failures = append(failures, "$ "+pass.Command+"\n[test file over piece target]\n"+strings.Join(slow, "\n"))
		}
	}
	return refused, strings.Join(failures, "\n\n"), nil
}

// origins is each file the change on checkout adds or edits since base, by its path at HEAD: its
// path on base, "" for one it adds, Python's suite_times.origins.
func origins(checkout, base string) (map[string]string, error) {
	listed, err := gitcall.Git{Repo: checkout}.Must("diff", "--find-renames", "--name-status", "-z", base+"...HEAD")
	if err != nil {
		return nil, err
	}
	fields := strings.Split(listed, "\x00")
	found := map[string]string{}
	for len(fields) > 1 && fields[0] != "" { // the NUL ending the last record leaves an empty one
		status, old := fields[0], fields[1]
		path := old
		if fields = fields[2:]; strings.HasPrefix(status, "R") && len(fields) > 0 {
			path, fields = fields[0], fields[1:]
		}
		switch status {
		case "D":
		case "A":
			found[path] = ""
		default:
			found[path] = old
		}
	}
	return found, nil
}

// said is seconds as Python's `:g` writes them.
func said(seconds float64) string {
	return strconv.FormatFloat(seconds, 'g', 6, 64)
}
