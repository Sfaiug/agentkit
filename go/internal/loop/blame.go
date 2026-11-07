package loop

// The blame walk, Python's land._blame_tip: once the target's own red has its repair, which waits on
// no blame, as no blame waits on the repair's outcome, the first red commit of the target's
// first-parent line is found by halving, and the run that merged it is blamed after its merge, once
// (history.BlameMerge).  It reaches back blameReach commits at most, six steps, none older than
// keepEvidence, the tip last, red twice already.  Each step checks its commit as the probe checked
// the tip, the tests that failed again alone first where those decided it, the piece where none of
// them failed there again.  Exits decide, never names: a step red on every go of a piece is red, one
// that passes is green, and a go that failed beside one that passed is a flake, which ends the walk
// without blame, as does a step that proves nothing.  Red at the oldest commit blames nobody.

import (
	"cmp"
	"errors"
	"fmt"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/gitcall"
	"agentkit/internal/history"
	"agentkit/internal/host"
)

const blameReach = 64

// blameTip is that walk from the target's tip, of the red piece of suite ("" for the suite whole)
// and the tests that failed again alone there, if any, the stack's checkout put back on the tip
// however it ends.  What fails it but a stop ends it without blame, said.
func (s *narrowingStack) blameTip(tip, suite, piece string, tests []string) (err error) {
	defer func() {
		if err != nil && !errors.Is(err, errStop) {
			s.l.say("WARN could not find the target's first red commit: " + err.Error())
			err = nil
		}
		err = cmp.Or(err, s.putBack(tip))
	}()
	listed, err := gitcall.Git{Repo: s.checkout.path}.Must("rev-list", "--first-parent", fmt.Sprintf("--max-count=%d", blameReach),
		fmt.Sprintf("--since=@%d +0000", int64(clock()-keepEvidence.Seconds())), tip)
	if err != nil || listed == "" {
		return err
	}
	commits := strings.Fields(listed)
	slices.Reverse(commits)
	low, high := -1, len(commits)-1
	for high-low > 1 {
		mid := (low + high) / 2
		red, err := s.blameStep(commits[mid], suite, piece, tests)
		if err != nil || red == nil {
			return err
		}
		if *red {
			high = mid
		} else {
			low = mid
		}
	}
	if high == 0 {
		s.l.say(fmt.Sprintf("red before %s: nobody is blamed", commits[0][:12]))
		return nil
	}
	sha := commits[high]
	if name := history.BlameMerge(sha, "tip", s.l.say); name != "" {
		s.l.say(fmt.Sprintf("%s first turned the target red: %s", sha[:12], name))
	} else {
		s.l.say(fmt.Sprintf("%s merged outside ak: no history row to blame", sha[:12]))
	}
	return nil
}

// blameStep is whether sha is red, as the walk reads its check, nil for a step that ends the walk,
// said.  Tests the commit lacks are never named as run, a red their names cannot confirm: the piece
// then decides.  A check handed on proves nothing of the commit, as Python's on a moved checkout.
func (s *narrowingStack) blameStep(sha, suite, piece string, tests []string) (*bool, error) {
	name := "tip-" + sha + ".log"
	tries := [][]string{nil}
	if len(tests) > 0 {
		tries = [][]string{tests, nil}
	}
	passed := func(exit *int) bool { return exit != nil && *exit == 0 }
	flaky := func(goes []*int) bool {
		return slices.ContainsFunc(goes, passed) && slices.ContainsFunc(goes, func(exit *int) bool { return !passed(exit) })
	}
	var selection *checkSelection
	ok := false
	for _, only := range tries {
		if err := s.putBack(sha); err != nil {
			return nil, err
		}
		selection = &checkSelection{shard: piece, tests: only}
		var err error
		if ok, _, _, err = s.l.checkTree(s.checkout.path, []string{suite}, name, "tip", suite, selection); err != nil {
			return nil, err
		}
		if !selection.handoff {
			if err := s.flaked(selection, filepath.Join(s.dir, name)); err != nil {
				return nil, err
			}
		}
		if selection.handoff {
			ok, selection.exits, selection.red = false, nil, nil
		}
		if len(selection.flaky) > 0 || slices.ContainsFunc(selection.exits, flaky) {
			s.l.say(fmt.Sprintf("%s is flaky: nobody is blamed", sha[:12]))
			return nil, nil
		}
		if ok || only == nil || (selection.red != nil && selection.red.Has("tests")) {
			break
		}
	}
	repeated := slices.ContainsFunc(selection.exits, func(goes []*int) bool {
		return len(goes) >= 2 && !slices.ContainsFunc(goes, func(exit *int) bool { return exit == nil || *exit <= 0 })
	})
	if len(selection.exits) == 0 || (selection.red != nil && selection.red.Truthy("short")) || (!ok && !repeated) {
		s.l.say(fmt.Sprintf("%s has no repeated red: nobody is blamed", sha[:12]))
		return nil, nil
	}
	red := !ok
	return &red, nil
}

// went is goes with one more go's exit as its process ended, Python's raw exits, which no name
// decides: its row's (exitOf), but 0 for a pass that a test it never named as run turned red, so a
// test the tree lacks hides no flake.  A go that answered busy never ran.
func went(goes []*int, ended ran, err error) []*int {
	exit := exitOf(ended, err)
	switch {
	case exit != nil && *exit == host.SuiteBusy:
		return goes
	case exit != nil && ended.unnamed:
		exit = new(int)
	}
	return append(goes, exit)
}
