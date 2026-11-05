package loop

import (
	"cmp"
	"strings"

	"agentkit/internal/run"
	"agentkit/internal/task"
)

// ranChecks is the done-when as the run's rounds ran it, settled as the loop settles it: the
// task's lines, the target's suite as the one `# once` line of a run that lands.
func ranChecks(record *run.Object, cmds []string) []string {
	landing, suite := placeOf(record).landing()
	return declaredChecks(record, task.RoundCommands(cmds, suite, landing))
}

// shownChecks is the done-when as result.md shows it, Python's result_done_when: each `# once`
// line marked with where it ran, as the final check's record says.
func shownChecks(record *run.Object, cmds []string) []string {
	final := cmp.Or(record.Dict("final_check"), run.NewObject())
	where := final.Str("where")
	if where == "" && final.Truthy("outcome") {
		where = "landing"
	}
	suffix := "(once)"
	switch {
	case where == "round" && final.Truthy("round"):
		suffix = "(once, in round " + run.Text(final.Get("round")) + ")"
	case where == "round":
		suffix = "(once, in round)"
	case where == "landing":
		suffix = "(once, at landing)"
	}
	shown := make([]string, len(cmds))
	for i, cmd := range cmds {
		if bare, once := task.SplitOnce(cmd); once && !strings.Contains(bare, "(once") {
			cmd = bare + " " + suffix
		}
		shown[i] = cmd
	}
	return shown
}

// finalLine is result.md's `final check:` line, Python's final_check_line.
func finalLine(record *run.Object, cmds []string) string {
	if line := run.FinalChecked(record); line != "" {
		return line
	}
	if _, once := task.Group(cmds); len(once) > 0 {
		return "final check: not run"
	}
	return "final check: none (no once-commands)"
}
