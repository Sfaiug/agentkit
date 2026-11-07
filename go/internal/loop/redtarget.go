package loop

// A red target holds its line, Python's land._probe_tip, paused and _repair: nothing lands on a
// target that fails its own suite.  The first stack's red suite piece runs again on the target's tip
// alone before anyone is blamed.  Red there, the line's `.green` keeps it under the target's tree,
// its probes counted, and the line waits on the retry ladder, the piece probed again at each step.
// Red through the whole ladder, or the stack's tests failing again there alone, it is the target's
// own and gets one repair run, owned by the member probed, a PR's own seat being its fixer instead,
// and the commit that turned it red is blamed (blame.go); while it stays red, that repair alone is
// checked, on it.

import (
	"cmp"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/handback"
	"agentkit/internal/run"
)

// A lineTarget is the target a lander pass checks its line on, Python's check_line's target and
// tip_green: its remote branch, tip and the tip's tree, and the pieces of its suite the tip passed
// alone on this pass.
type lineTarget struct {
	upstream, tip, tree string
	green               map[string]bool
}

// paused is whether that red holds the line on the retry ladder, Python's paused: probed red on the
// tip alone, with no repair started and the ladder not yet climbed.  One an earlier lander kept
// counts no probes: it is the target's own, as that lander judged.
func paused(red *run.Object) bool {
	if red == nil || red.Truthy("run") {
		return false
	}
	probes, _ := red.Int("probes")
	return 0 < probes && probes <= len(transientBackoff)
}

// meet is what the target's red asks of m, a member ready for its verdict, Python's check_line: the
// line waits (held) for the ladder's next step, on a probe red again, or on a repair that cannot
// start; with the target's repair open, its run's name, every member but it is passed over and it is
// checked alone.  A PR waits on no repair: its own tree is checked, and lands if it mends the target.
func (t *lineTarget) meet(turn, code, repo string, m member, said io.Writer) (repair string, held bool, err error) {
	red := evidence(turn, "red").Dict(t.tree)
	if paused(red) {
		probes, _ := red.Int("probes")
		at, _ := red.Num("at")
		if clock()-at < transientDelay(probes).Seconds() {
			return "", true, nil
		}
		checkout, failed, err := scratchAt(repo, t.tip)
		if checkout != nil {
			defer checkout.close()
		}
		if err != nil {
			return "", true, err
		}
		if failed != "" {
			lines := config.SplitLines(failed)
			fmt.Fprintf(said, "WARN %s\n", lines[len(lines)-1])
			return "", true, nil
		}
		probe := cmp.Or(red.Dict("probe"), run.NewObject())
		stack := &narrowingStack{member: m, l: memberLoop(m, said), checkout: checkout}
		if passed, err := stack.probeTip(turn, code, t, probe.Str("command"), probe.Str("piece"), nil); err != nil || !passed {
			return "", true, err
		}
		red = nil
	}
	if red == nil || m.record.Truthy("review_pr") || cmp.Or(evidence(turn, "trees").Dict(t.tree), run.NewObject()).Str("tested") == t.tree {
		return "", false, nil
	}
	repair = red.Str("run")
	var current *run.Object
	if repair != "" {
		current, _ = run.Read(filepath.Join(run.Runs(), repair))
	}
	switch {
	case current == nil:
		repair = memberLoop(m, said).repairTarget(turn, t.tree, m.record, red)
		return repair, repair == "", nil
	case !handback.RepairOpen(current, cmp.Or(red.Dict("probe"), run.NewObject()).Str("sha")):
		return "", false, nil // a target that moved past its repair's end is a new red
	}
	return repair, false, nil
}

// probeTip runs the red piece of suite ("" for the suite whole) on the target's tip alone, the
// stack's checkout put there, for its member, Python's _probe_tip: whether it passes there, the red
// then the member's own and the piece the target's green.  Where the stack's red was its tests
// failing again alone, those alone run there first: passing, the member's change is what fails them;
// failing again, they are a red that repeats, which no step of the ladder would clear, and the piece
// need not run.  Anything else proves nothing, and the piece decides.  A piece with no verdict there,
// handed on or out of memory, holds the line as it found it, for the next pass to probe again.
func (s *narrowingStack) probeTip(turn, code string, target *lineTarget, suite, piece string, tests []string) (bool, error) {
	probe := func(selection *checkSelection) (*run.Object, error) {
		if err := s.putBack(target.tip); err != nil {
			return nil, err
		}
		return s.check([]string{suite}, suite, "tip", selection)
	}
	tip := target.tip[:min(12, len(target.tip))]
	var again []string
	if len(tests) > 0 {
		selection := &checkSelection{shard: piece, tests: tests}
		answer, err := probe(selection)
		switch {
		case err != nil || selection.handoff:
			return false, err
		case answer == nil: // proves nothing: the piece decides
		case answer.Has("land"):
			s.l.say(fmt.Sprintf("%s at %s passes the tests that failed %s's piece AK_SHARD=%s, run alone: the red is the member's own",
				target.upstream, tip, s.l.id, piece))
			return true, nil
		default:
			again = names(answer.Dict("fix").List("tests"))
		}
	}
	if len(again) == 0 {
		answer, err := probe(&checkSelection{shard: piece})
		if err != nil || answer == nil {
			return false, err
		}
		if answer.Has("land") {
			check := suite
			if piece != "" {
				check = fmt.Sprintf("%s (AK_SHARD=%s)", suite, piece) // the piece's pass covers no stack's own checks
			}
			note(turn, func(trees, red, _ *run.Object) {
				trees.Set(target.tree, run.Fields("at", clock(), "tested", target.tree, "leader", s.l.id, "checks", toList([]string{check}), "code", codeValue(code)))
				red.Delete(target.tree)
			})
			target.green[piece] = true
			return true, nil
		}
	}
	output, err := os.ReadFile(filepath.Join(s.dir, "target-probe.log"))
	if err != nil {
		return false, err
	}
	text, err := redTargetText(suite, target.upstream, target.tip, decoded(output), s.dir, piece)
	if err != nil {
		return false, err
	}
	probes := len(transientBackoff) + 1 // a repeat is the whole ladder climbed: never a pause
	if held := evidence(turn, "red").Dict(target.tree); len(again) == 0 {
		probes = 1
		if held != nil && cmp.Or(held.Dict("probe"), run.NewObject()).Str("sha") == target.tip {
			counted, _ := held.Int("probes")
			probes = counted + 1
		}
	}
	entry := run.Fields("probe", run.Fields("command", suite, "piece", piece, "check", suite+"  # once", "sha", target.tip, "text", text),
		"at", clock(), "probes", probes)
	note(turn, func(trees, red, _ *run.Object) {
		red.Set(target.tree, entry)
		trees.Delete(target.tree) // a target found red holds no earlier pass
	})
	what := "its suite"
	if piece != "" {
		what = "its piece AK_SHARD=" + piece
	}
	if probes <= len(transientBackoff) {
		s.l.say(fmt.Sprintf("%s at %s fails %s alone: the line waits, nobody is blamed; probed again in %d min",
			target.upstream, tip, what, int(transientDelay(probes).Minutes())))
		return false, nil
	}
	how := what + " alone through the retry ladder"
	if len(again) > 0 {
		how = strings.Join(again, " ") + " of " + what + " again, run alone"
	}
	s.l.say(fmt.Sprintf("%s at %s fails %s: the target's own red, repaired", target.upstream, tip, how))
	s.l.repairTarget(turn, target.tree, s.record, entry)
	return false, s.blameTip(target.tip, suite, piece, again)
}

// repairTarget is the one repair of the red the line keeps under tree, owned by the member whose
// record that is and whose run this loop is, Python's _repair: started, or already open, its name
// kept on the red; "" for none.  A PR's own seat is its fixer, as for its review findings: it never
// gets a repair run, and is handed the red as its landing finding, which the pass's wake takes to it.
func (l *loop) repairTarget(turn, tree string, record, red *run.Object) string {
	probe := cmp.Or(red.Dict("probe"), run.NewObject())
	if record.Truthy("review_pr") {
		path := filepath.Join(l.dir, "target-red.log")
		if os.WriteFile(path, []byte(probe.Str("text")+"\n"), 0o666) == nil {
			publish(l.dir, record, run.Fields("fix", run.Fields("line", strings.Split(probe.Str("text"), "\n")[0], "log", path)), l.voice)
		}
		return ""
	}
	name, err := handback.StartRepair(record, l.dir, probe, launchForSeat, l.say)
	if err != nil {
		l.say("WARN no repair could start: " + err.Error()) // the line waits, unblamed
	}
	if name != "" {
		note(turn, func(trees, reds, _ *run.Object) {
			reds.Set(tree, run.SetAll(red.Copy(), "run", name))
			trees.Delete(tree)
		})
	}
	return name
}

// redTargetText is what a red target's repair is told, Python's prompts.red_target_text: the command
// (its red piece where the suite ran in pieces), where it fails, and what it printed there, indented
// as a fixer reads a failed check, so nothing it printed reads as a heading or a fence of the task.
func redTargetText(cmd, upstream, tip, output, where, piece string) (string, error) {
	shown, err := failingBlocks(output, where)
	if err != nil {
		return "", err
	}
	var printed []string
	for _, line := range config.SplitLines(shown) {
		printed = append(printed, "    "+line)
	}
	what := "`" + cmd + "`"
	if piece != "" {
		what += ", its piece AK_SHARD=" + piece + ","
	}
	return fmt.Sprintf("%s fails on %s at %s, the target's own tip, whichever branch runs it. What it printed there:\n\n%s",
		what, upstream, tip, strings.Join(printed, "\n")), nil
}
