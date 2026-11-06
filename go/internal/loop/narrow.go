package loop

// Narrowing hides the search between a red stack and the last tree green on what failed.
// Whole checks, evidence, publication and delivery remain the line's own steps. Named tests
// passing alone are search evidence only: below each culprit a whole check must cover the
// surviving prefix before the rebuilt suffix runs. Each check keeps what it saw of flaky tests
// (flakes.go). Reds with suite helpers, reviews of PRs other than a seat's own, changed-file suites
// and target repairs stay with Python, as do integration or rules refusals on a stack.

import (
	"context"
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/helper"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

type narrowingStack struct {
	member
	l        *loop
	checkout *landingCheckout
	head     string
	tree     string
	checks   []string
}

// withCandidates checks the pass's unwoken records under the same recovery locks publication
// takes. Already published greens may deliver during a check, retaining their reviewed work.
func withCandidates(prefix, pending []member, action func() bool) bool {
	return withPrefix(prefix, func() bool {
		for _, m := range pending {
			release, err := run.Hold(m.dir)
			if err != nil {
				return false
			}
			defer release()
			current, _ := run.Read(m.dir)
			if !run.Equal(current, m.record) || run.ProcessActive(current) {
				return false
			}
		}
		return action()
	})
}

// redBehind is whether a red on a stack still waits on runs in the line, members.
func redBehind(wait *run.Object, members []member) bool {
	if !wait.Has("fix") || wait.Has("land") {
		return false
	}
	after := wait.Dict("after")
	return after != nil && slices.ContainsFunc(members, func(m member) bool { return after.Has(filepath.Base(m.dir)) })
}

// narrowLine checks the line's ready stack, Python's check_line: a member that changed or runs keeps
// its place, a green delivery ahead in the stack, a red is the pass's wake's, a saved green wakes
// again, and the first member with no verdict is checked with every later one ready for it.
func narrowLine(turn, code, repo, tip, upstream string, members []member, said io.Writer) error {
	var prefix, pending []member
	for index, m := range members {
		wait := m.record.Dict("waiting_on")
		if run.ProcessActive(m.record) || !unchanged(m.dir, m.record) {
			if green(wait) {
				prefix = append(prefix, m)
			}
			continue
		}
		if wait.Has("fix") {
			continue
		}
		if m.record.Str("state") != "waiting" {
			prefix = append(prefix, m) // a green delivery the tick resumes
			continue
		}
		if pythons(m.record) {
			return nil
		}
		if green(wait) {
			withPrefix(prefix, func() bool { return publish(m.dir, m.record, wait, said) })
			prefix = append(prefix, m)
			continue
		}
		if !reviewPassed(m.record) {
			continue
		}
		pending = append(pending, m)
		for _, later := range members[index+1:] {
			wait := later.record.Dict("waiting_on")
			if later.record.Str("state") != "waiting" || wait.Has("fix") || wait.Has("land") || !reviewPassed(later.record) ||
				run.ProcessActive(later.record) || !unchanged(later.dir, later.record) {
				continue
			}
			if pythons(later.record) {
				break // the stack ends short of it
			}
			pending = append(pending, later)
		}
		break
	}
	pending = unmoved(prefix, pending, said)
	below := -1
	for len(pending) > 0 {
		if !withCandidates(prefix, pending, func() bool { return true }) {
			return nil
		}
		stacks, err := buildNarrowing(repo, tip, upstream, prefix, pending, said)
		if err != nil || len(stacks) == 0 {
			closeNarrowing(stacks)
			return err
		}
		culprit, landed, err := narrowStacks(turn, code, tip, prefix, stacks, below, said)
		closeNarrowing(stacks)
		if err != nil || culprit < 0 {
			return err
		}
		pending = nil
		for index, stack := range stacks {
			if index < landed {
				prefix = append(prefix, stack.member)
			} else if index != culprit {
				pending = append(pending, stack.member)
			}
		}
		below = culprit - landed - 1
	}
	return nil
}

func reviewPassed(record *run.Object) bool {
	review := record.Dict("review")
	return review != nil && review.Str("verdict") == "PASS"
}

func buildNarrowing(repo, tip, upstream string, prefix, pending []member, said io.Writer) (stacks []*narrowingStack, err error) {
	top := tip
	for _, m := range prefix {
		top, err = (&loop{dir: m.dir}).prefixTop(m.record, repo, tip, upstream, top)
		if err != nil || top == "" {
			return nil, err
		}
	}
	for _, m := range pending {
		l := &loop{ctx: context.Background(), dir: m.dir, id: filepath.Base(m.dir), voice: said, line: landingLine(m.record),
			silence: minutes(m.record, "silence_minutes", run.SilenceMinutes), ceiling: time.Duration(number(m.record, "ceiling_hours", run.CeilingHours) * float64(time.Hour))}
		checkout, failure, err := l.stackMember(m.record, repo, tip, top, upstream)
		if err != nil || failure != nil {
			if checkout != nil {
				checkout.close()
			}
			if err == nil && top == tip {
				withCandidates(prefix, pending, func() bool { return publish(m.dir, m.record, failure, said) })
			}
			return stacks, err
		}
		stack := &narrowingStack{member: m, l: l, checkout: checkout}
		stacks = append(stacks, stack)
		place := &repoPlace{wt: checkout.path, baseSHA: tip}
		if failure, err := place.rulesCheck(); err != nil || failure != "" {
			checkout.close()
			if err == nil && top == tip {
				withCandidates(prefix, pending, func() bool { return publish(m.dir, m.record, l.fixed("lander.log", failure+"\n", false), said) })
			}
			return stacks[:len(stacks)-1], err
		}
		stack.head, stack.tree, err = place.identity()
		if err != nil {
			return stacks, err
		}
		stack.checks, err = landingChecks(m, checkout.path, tip)
		if err != nil || slices.ContainsFunc(stack.checks, namesChanged.MatchString) {
			checkout.close()
			return stacks[:len(stacks)-1], err
		}
		top = stack.head
	}
	return stacks, nil
}

func closeNarrowing(stacks []*narrowingStack) {
	for _, stack := range stacks {
		stack.checkout.close()
	}
}

// check runs the checks as a check of kind, `landing`, or `tip` for a probe of the target's.
func (s *narrowingStack) check(checks []string, suite, kind string, selection *checkSelection) (*run.Object, error) {
	name := fmt.Sprintf("lander-%s.log", s.tree)
	switch {
	case kind == "tip":
		name = "target-probe.log"
	case selection.pinned():
		name = fmt.Sprintf("lander-%s-tests.log", s.tree)
	}
	defer func() {
		if selection.handoff {
			selection.rows.Drop(s.l.say) // Python checks it again, and records it then
		}
	}()
	ok, line, failing, err := s.l.checkTree(s.checkout.path, checks, name, kind, suite, selection)
	if errors.Is(err, helper.ErrPython) || errors.Is(err, errTurnPython) || err == nil && !ok && !selection.pinned() && helper.May() {
		// a whole check's red with suite helpers is Python's, as stack.go says
		selection.handoff, err = true, nil
	}
	if err != nil || selection.handoff {
		return nil, err
	}
	if err := s.flaked(selection, filepath.Join(s.dir, name)); err != nil || selection.handoff {
		return nil, err
	}
	if ok {
		return run.Fields("land", s.tree), nil
	}
	if s.short(selection) {
		return nil, nil
	}
	if selection.tests != nil && (selection.red == nil || !selection.red.Has("tests")) {
		return nil, nil // a missing or unconfirmed test needs the stack's whole check
	}
	fix := run.Fields("line", line, "log", filepath.Join(s.dir, name), "command", failing, "piece", "")
	if selection.red != nil {
		run.SetAll(fix, pairs(selection.red)...)
	}
	return run.Fields("fix", fix), nil
}

func (s *narrowingStack) checkTests(command, suite string, selection *checkSelection) (*run.Object, error) {
	answer, err := s.check([]string{command}, suite, "landing", selection)
	if err == nil {
		err = s.putBack(s.head)
	}
	return answer, err
}

func narrowStacks(turn, code, tip string, prefix []member, stacks []*narrowingStack, below int, said io.Writer) (int, int, error) {
	suite := gitcall.Suite(stacks[0].checkout.path, tip)
	limit := host.Pieces(0, 0)
	if pinned, _ := config.MaxGates(); pinned > 0 {
		limit = pinned
	}
	batched := namesShard.MatchString(suite) || len(stacks) > limit || below >= 0
	accepted := 0
	valid := func(action func() bool) bool {
		ahead := append([]member{}, prefix...)
		var pending []member
		for index, stack := range stacks {
			if index < accepted {
				ahead = append(ahead, stack.member)
			} else {
				pending = append(pending, stack.member)
			}
		}
		return withCandidates(ahead, pending, action)
	}
	commands := func(index int) []string {
		var checks []string
		for _, stack := range stacks[:index+1] {
			for _, command := range stack.checks {
				if command != suite && !slices.Contains(checks, command) {
					checks = append(checks, command)
				}
			}
		}
		if suite != "" {
			checks = append(checks, suite)
		}
		return checks
	}
	publishAt := func(index int, answer *run.Object) bool {
		after := run.NewObject()
		for _, m := range prefix {
			after.Set(filepath.Base(m.dir), m.record.Dict("waiting_on").Get("land"))
		}
		for _, stack := range stacks[:index] {
			after.Set(filepath.Base(stack.dir), stack.tree)
		}
		answer.Set("after", after)
		stack := stacks[index]
		return valid(func() bool {
			if !publish(stack.dir, stack.record, answer, said) {
				return false
			}
			stack.record, _ = run.Read(stack.dir)
			return true
		})
	}
	whole := func(index int) (*run.Object, error) {
		if !valid(func() bool { return true }) {
			return nil, nil
		}
		checks := commands(index)
		covered := stacks[:index+1]
		if !batched {
			checks, covered = stacks[index].checks, stacks[index:index+1]
		}
		cached := answering(turn, code, "trees").Dict(stacks[index].tree)
		answer := run.Fields("land", stacks[index].tree)
		var err error
		if cached == nil || cached.Str("tested") != stacks[index].tree || !covers(cached.List("checks"), checks) {
			cached = nil
			answer, err = stacks[index].check(checks, suite, "landing", &checkSelection{})
		}
		if err != nil || answer == nil {
			return answer, err
		}
		note(turn, func(trees, _, red *run.Object) {
			entry := run.Fields("at", clock(), "leader", filepath.Base(stacks[index].dir), "checks", toList(checks), "code", codeValue(code))
			if cached != nil {
				entry = cached.Copy()
			}
			if answer.Has("fix") {
				red.Set(stacks[index].tree, run.SetAll(entry, pairs(answer.Dict("fix"))...))
			} else {
				entry.Set("tested", stacks[index].tree)
				for _, stack := range covered {
					trees.Set(stack.tree, entry.Copy())
				}
			}
		})
		if answer.Has("land") {
			for accepted <= index {
				green := run.Fields("land", stacks[accepted].tree)
				if accepted != index {
					green.Set("tested", stacks[index].tree)
				}
				if !publishAt(accepted, green) {
					return nil, nil
				}
				accepted++
			}
		}
		return answer, nil
	}
	passed := map[string]int{}
	for accepted < len(stacks) {
		if !valid(func() bool { return true }) {
			return -1, accepted, nil
		}
		index := len(stacks) - 1
		if !batched {
			index = accepted
		}
		if below >= accepted {
			index, below = below, -1
		}
		answer, err := whole(index)
		if err != nil || answer == nil {
			return -1, accepted, err
		}
		for answer.Has("fix") {
			fix := answer.Dict("fix")
			command, tests := fix.Str("command"), names(fix.List("tests"))
			key := command + "\x00" + strings.Join(tests, "\x00")
			low := accepted - 1
			if previous, ok := passed[key]; ok && previous < index {
				low = max(low, previous)
			}
			if low+1 == index {
				if index == 0 && len(prefix) == 0 && command == suite {
					ok, err := stacks[index].probeTarget(tip, suite, fix)
					if err != nil || !ok {
						return -1, accepted, err
					}
				}
				if !publishAt(index, answer) {
					return -1, accepted, nil
				}
				return index, accepted, nil
			}
			owner := slices.IndexFunc(stacks, func(stack *narrowingStack) bool { return slices.Contains(stack.checks, command) })
			middle := (max(low, owner-1) + index) / 2
			runs := command
			if middle < owner {
				runs = ""
				if len(tests) > 0 {
					runs = suite
				}
			}
			selection := &checkSelection{shard: fix.Str("piece"), tests: tests}
			if runs == "" {
				answer, err = whole(middle)
			} else if valid(func() bool { return true }) {
				answer, err = stacks[middle].checkTests(runs, suite, selection)
				if answer == nil && err == nil && !selection.handoff {
					answer, err = whole(middle)
				}
			} else {
				return -1, accepted, nil
			}
			if err != nil || answer == nil {
				return -1, accepted, err
			}
			if answer.Has("land") {
				passed[key] = middle
				answer = run.Fields("fix", fix)
			} else {
				index = middle
			}
		}
	}
	return -1, accepted, nil
}

func (s *narrowingStack) probeTarget(tip, suite string, fix *run.Object) (bool, error) {
	if err := s.putBack(tip); err != nil {
		return false, err
	}
	selection := &checkSelection{shard: fix.Str("piece"), tests: names(fix.List("tests"))}
	answer, err := s.check([]string{suite}, suite, "tip", selection)
	if answer == nil && err == nil && !selection.handoff {
		if err := s.putBack(tip); err != nil {
			return false, err
		}
		answer, err = s.check([]string{suite}, suite, "tip", &checkSelection{shard: fix.Str("piece")})
	}
	return answer != nil && answer.Has("land"), err
}

func (s *narrowingStack) putBack(head string) error {
	in := gitcall.Git{Repo: s.checkout.path}
	if _, err := in.Must("checkout", "--force", "--detach", head); err != nil {
		return err
	}
	_, err := in.Must("clean", "-fdx")
	return err
}
