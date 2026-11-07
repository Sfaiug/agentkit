package loop

// Narrowing hides the search between a red stack and the last tree green on what failed.
// Whole checks, evidence, publication and delivery remain the line's own steps. Named tests
// passing alone are search evidence only: below each culprit a whole check must cover the
// surviving prefix before the rebuilt suffix runs. Each check keeps what it saw of flaky tests
// (flakes.go). Named tests that failed probe the stacks between on the suite helpers, many at
// once (probes.go), and only the step that decides the blame runs here. Probes on a machine ak may
// rent and reviews of PRs other than a seat's own stay with Python, as do
// integration or rules refusals on a stack.

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

// narrowLine checks the line's ready stack on its target, Python's check_line: a member that changed
// or runs keeps its place, a green delivery ahead in the stack, a red is the pass's wake's, a saved
// green wakes again, and the first member with no verdict is checked with every later one ready for
// it, as the target's red allows.
func narrowLine(turn, code, repo string, target *lineTarget, members []member, said io.Writer) error {
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
		repair, held, err := target.meet(turn, code, repo, m, said)
		if err != nil || held {
			return err
		}
		if repair != "" && repair != filepath.Base(m.dir) {
			continue
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
			if repair != "" {
				break // the target's repair is checked alone on it
			}
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
		stacks, err := buildNarrowing(repo, target.tip, target.upstream, prefix, pending, said)
		if err != nil || len(stacks) == 0 {
			closeNarrowing(stacks)
			return err
		}
		culprit, landed, err := narrowStacks(turn, code, target, prefix, stacks, below, said)
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
		l := memberLoop(m, said)
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
		if err != nil {
			checkout.close()
			return stacks[:len(stacks)-1], err
		}
		top = stack.head
	}
	return stacks, nil
}

// memberLoop is the loop the lander checks the member's trees with: its limits, saying what it does
// in the lander's output.
func memberLoop(m member, said io.Writer) *loop {
	return &loop{ctx: context.Background(), dir: m.dir, id: filepath.Base(m.dir), voice: said, line: landingLine(m.record),
		silence: minutes(m.record, "silence_minutes", run.SilenceMinutes), ceiling: time.Duration(number(m.record, "ceiling_hours", run.CeilingHours) * float64(time.Hour))}
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
	if errors.Is(err, helper.ErrPython) || errors.Is(err, errTurnPython) {
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

func narrowStacks(turn, code string, target *lineTarget, prefix []member, stacks []*narrowingStack, below int, said io.Writer) (int, int, error) {
	suite := gitcall.Suite(stacks[0].checkout.path, target.tip)
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
	// what failed, by the stacks it passed on alone, here or probed on a helper, and those a probe
	// found it red on
	passed, probed := map[string][]int{}, map[string][]int{}
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
			low, high := accepted-1, index
			// a probe's red bounds it sooner, though it blames nobody, until a pass here outweighs it
			for _, at := range probed[key] {
				if at > low && at < high && !slices.Contains(passed[key], at) {
					high = at
				}
			}
			for _, at := range passed[key] {
				if at < high {
					low = max(low, at)
				}
			}
			if low+1 == index {
				// The tip answers for a red suite before anyone is blamed, as the host may have
				// failed it; a repair lands on the red target, which is never probed for it.
				if index == 0 && len(prefix) == 0 && command == suite && !stacks[index].record.Truthy("repair") && !target.green[fix.Str("piece")] {
					if !valid(func() bool { return true }) {
						return -1, accepted, nil
					}
					ok, err := stacks[index].probeTip(turn, code, target, suite, fix.Str("piece"), tests)
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
			floor := max(low, owner-1)
			if len(tests) > 0 && floor+1 < high {
				// The stacks between go to the suite helpers, many at once, a round at a time; a round
				// that proves nothing leaves the step to this host.
				if config.MayRent() {
					return -1, accepted, nil // Python rents a machine for the probes
				}
				if !valid(func() bool { return true }) {
					return -1, accepted, nil
				}
				probes, err := round(stacks, floor, high, command, tests)
				if err != nil {
					return -1, accepted, err
				}
				for at, ok := range probes {
					if ok {
						passed[key] = append(passed[key], at)
					} else {
						probed[key] = append(probed[key], at)
					}
				}
				if len(probes) > 0 {
					continue
				}
			}
			// A probe's red right after a pass runs here: it decides the blame, with the flaky
			// handling a probe has none of, and passing here it moves the narrowing on above it.
			middle := (floor + high) / 2
			if low+1 == high {
				middle = high
			}
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
				passed[key] = append(passed[key], middle)
				answer = run.Fields("fix", fix)
			} else {
				index = middle
			}
		}
	}
	return -1, accepted, nil
}

func (s *narrowingStack) putBack(head string) error {
	in := gitcall.Git{Repo: s.checkout.path}
	if _, err := in.Must("checkout", "--force", "--detach", head); err != nil {
		return err
	}
	_, err := in.Must("clean", "-fdx")
	return err
}
