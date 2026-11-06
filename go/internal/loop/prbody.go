package loop

import (
	"cmp"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// prBody is what the PR says of the run, Python's pr_body: the task's goal and the checks that
// passed on the reviewed commit, the risks it accepted, how it got there, its follow-ups and
// notes, and the executor's own words last, within GitHub's limit.
func prBody(record *run.Object) string {
	latest := run.NewObject()
	summaries := record.List("round_summaries")
	if len(summaries) > 0 {
		if round, ok := summaries[len(summaries)-1].(*run.Object); ok {
			latest = round
		}
	}
	goal, cmds, accepted := "No task goal recorded.", []string(nil), []string(nil)
	if path := record.Str("task"); path != "" {
		if data, err := os.ReadFile(path); err == nil {
			text := task.Text(data)
			body := task.Body(text)
			for _, line := range config.SplitLines(task.Section(body, "Decided")) {
				if line = strings.TrimFunc(line, config.Space); strings.HasPrefix(line, "Accepted:") {
					accepted = append(accepted, line)
				}
			}
			said := task.Section(body, "Goal")
			if strings.TrimFunc(said, config.Space) == "" {
				said = "No Goal section recorded."
			}
			goal = task.Title(text, strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))) + "\n\n" + said
			_, cmds, _ = task.Read(path)
		}
	}
	lines := []string{"## Goal", "", goal, "", "## Testing", ""}
	if len(cmds) == 0 {
		lines = append(lines, "No done-when commands recorded.")
	} else {
		tested := "No passing done-when result on a reviewed commit recorded."
		if latest.Get("done_when") == true && latest.Truthy("head_sha") && latest.Truthy("round") {
			tested = fmt.Sprintf("Passed together in round %s on reviewed commit `%s`.", run.Text(latest.Get("round")), run.Text(latest.Get("head_sha")))
		}
		lines = append(append(append(lines, "```bash"), cmds...), "```", "", tested)
	}
	if len(accepted) > 0 {
		lines = append(lines, "", "## Risk", "")
		for _, line := range accepted {
			lines = append(lines, "- "+line)
		}
	}
	lines = append(lines, "", "---", "",
		"- verdict: "+run.Text(record.Get("verdict")),
		fmt.Sprintf("- rounds: %d of %s", len(summaries), run.Text(record.Get("rounds"))),
		"- executor: "+run.Text(record.Get("executor"))+", reviewer: "+run.Text(record.Get("reviewer")),
		"- run: "+run.Text(record.Get("run_id")))
	if line := baseProofLine(record); line != "" {
		lines = append(lines, "- "+line)
	}
	for _, section := range [][2]string{{"followups", "Follow-ups"}, {"notes", "Notes"}} {
		if items := record.List(section[0]); len(items) > 0 {
			lines = append(lines, "", "## "+section[1], "")
			for _, item := range items {
				lines = append(lines, "- "+strings.ReplaceAll(run.Text(item), "\n", "\n  "))
			}
		}
	}
	lines = append(lines, "", "## Executor's summary", "", cmp.Or(gitcall.Strip(latest.Str("summary")), "No executor summary recorded."))
	return githubBody(strings.Join(append(lines, ""), "\n"), record.Str("run_id"))
}
