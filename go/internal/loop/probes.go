package loop

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"

	"agentkit/internal/helper"
	"agentkit/internal/history"
)

// round is one round of a red stack's narrowing, Python's land._round: probes of the stacks
// between floor and high, as many as the suite helpers have places for, spread evenly and all at
// once, and whether just tests of command passed on each probed stack that proved either, once the
// last has ended; none where the helpers have no place.  Probes running the same tests end about
// together, so waiting for the last costs little, and none outlives its round: nothing is ever
// called off on a helper.
func round(stacks []*narrowingStack, floor, high int, command string, tests []string) (map[int]bool, error) {
	top := stacks[high]
	cpus, memory := suiteCost(top.dir, top.checkout.path, command)
	count := min(helper.Places(cpus, memory, top.checkout.path), high-floor-1)
	picked := make([]int, count)
	passed, proved, errs := make([]bool, count), make([]bool, count), make([]error, count)
	var probes sync.WaitGroup
	for n := range picked {
		picked[n] = floor + (n+1)*(high-floor)/(count+1)
		probes.Add(1)
		go func(n int) {
			defer probes.Done()
			passed[n], proved[n], errs[n] = stacks[picked[n]].probe(command, tests, cpus, memory)
		}(n)
	}
	probes.Wait()
	answers, said := map[int]bool{}, make([]string, count)
	for n, index := range picked {
		said[n] = "proves nothing"
		if proved[n] {
			answers[index], said[n] = passed[n], map[bool]string{true: "passes", false: "fails"}[passed[n]]
		}
		said[n] += " up to " + filepath.Base(stacks[index].dir)
	}
	if count > 0 {
		top.l.say(strings.Join(tests, " ") + " on the suite helpers: " + strings.Join(said, ", "))
	}
	return answers, errors.Join(errs...)
}

// probe is whether just tests of command pass on the stack, run once on a suite helper as one piece
// of that cost, Python's land._probe: passed where each was named as run (AK_RAN), not where the
// run failed naming one of them both as run and as failed (AK_FAILED), and not proved where it
// proved neither -- no helper took it, it hung, the helper lost it or had no room, a test was not
// named as run.  It leaves its row in history and records nothing else, no flaky sighting either: a
// red only a helper shows is no evidence (the step here decides).
func (s *narrowingStack) probe(command string, tests []string, cpus, memory float64) (passed, proved bool, err error) {
	asked := clock()
	away, err := helper.Probe(s.checkout.path, cpus, memory, command, tests)
	if away == nil || err != nil {
		return false, false, err
	}
	defer away.Finish()
	out, err := os.Create(filepath.Join(s.dir, fmt.Sprintf("lander-%s-probe.log", s.tree)))
	if err != nil {
		return false, false, err
	}
	defer out.Close()
	row := history.Check(&history.Checked{Run: s.l.id, Kind: "landing", Tree: s.head}, command, asked, away.Alias, s.l.say)
	// a hang ends as a suite piece's first go does, at its suite's pace: its round waits for it
	code, stopped, err := s.l.onHelper(away, "1/1", s.l.ceiling, out)
	row.End(exitOf(ran{code: code, stopped: stopped}, err))
	if err != nil || stopped != "" || code < 0 || helper.Gone(code) {
		return false, false, err
	}
	named := away.Named("1/1", "ran")
	if code == 0 {
		return true, !slices.ContainsFunc(tests, func(test string) bool { return !slices.Contains(named, test) }), nil
	}
	failed := away.Named("1/1", "failed")
	return false, slices.ContainsFunc(tests, func(test string) bool {
		return slices.Contains(named, test) && slices.Contains(failed, test)
	}), nil
}
