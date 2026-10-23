package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

const runFlagsUsage = "ak run <task.md> [--rounds N] [--exec MODEL] [--review MODEL] [--anyway] [--first] [--no-worktree] [--no-merge] [--bg] [--parallel N] | ak run --review-pr <url> [--review MODEL] [--first] [--bg]"
const runUsage = "usage: ak run <task.md> [--rounds N] [--exec MODEL] [--review MODEL] [--anyway] [--first] [--no-worktree] [--no-merge] [--bg] [--parallel N] | ak run --review-pr <url> | ak run status [<runid>] | ak run resume <runid> | ak run stop <runid> [--keep] | ak run clean <runid> | ak run gc"

var pullURL = regexp.MustCompile(`^https://github\.com/[^/\s]+/[^/\s]+/pull/[0-9]+/?$`)

func runSubcommand(args []string) bool {
	return len(args) > 0 && contains([]string{"--lander", "status", "show", "clean", "gc", "resume", "merge", "stop"}, args[0])
}

func validateRun(args []string) string {
	if runSubcommand(args) {
		return validateRunSubcommand(args[0], args[1:])
	}
	parsed, problem := parse(args, []string{"--rounds", "--exec", "--review", "--review-pr", "--parallel"},
		[]string{"--no-worktree", "--no-merge", "--bg", "--anyway", "--first"}, runFlagsUsage)
	if problem != "" {
		return problem
	}
	seat := os.Getenv("AGENTKIT_SESSION")
	if seat != "" && os.Getenv("AGENTKIT_RUN_DIR") == "" && isFile(filepath.Join(config.Home(), "state", "session-"+seat+".json")) {
		var given []string
		for _, flag := range []string{"--exec", "--review", "--anyway", "--first"} {
			if parsed.values[flag] != "" || parsed.flags[flag] {
				given = append(given, flag)
			}
		}
		if len(given) > 0 {
			return strings.Join(given, ", ") + ": not a seat's; ak picks the models, decides what goes first and refuses a second run of a change under way, so launch without"
		}
	}
	if url := parsed.values["--review-pr"]; url != "" {
		_, parallel := parsed.values["--parallel"]
		if len(parsed.words) > 0 || parsed.values["--rounds"] != "" || parsed.values["--exec"] != "" || parsed.flags["--no-worktree"] || parallel {
			return "usage: ak run --review-pr <url> [--review MODEL] [--first] [--bg]: no task file, no executor, no rounds"
		}
		if !pullURL.MatchString(url) {
			return fmt.Sprintf("--review-pr needs a GitHub PR URL (got %s)", repr(url))
		}
	} else if len(parsed.words) == 0 {
		return runUsage
	}
	for _, flag := range []string{"--rounds", "--parallel"} {
		if value, ok := parsed.values[flag]; ok {
			if !positive(value) {
				return fmt.Sprintf("%s must be a positive integer (got %s)", flag, repr(value))
			}
			if flag == "--rounds" {
				if problem := rounds(value); problem != "" {
					return problem
				}
			}
		}
	}
	if err := config.Check(); err != nil {
		return err.Error()
	}
	if _, parallel := parsed.values["--parallel"]; parallel && len(parsed.words) == 1 {
		return "usage: ak run <task.md> [--rounds N] [--exec MODEL] [--review MODEL] [--anyway] [--first] [--no-worktree] [--no-merge] [--bg]: --parallel needs more than one task file"
	}
	for _, task := range parsed.words {
		if path := config.Absolute(task); !isFile(path) {
			return "no such task file: " + path
		}
	}
	return ""
}

func validateRunSubcommand(verb string, args []string) string {
	if verb == "--lander" {
		if len(args) != 1 || filepath.Base(args[0]) != args[0] || !strings.HasPrefix(args[0], ".merge-") {
			return "usage: ak run --lander LINE"
		}
		return ""
	}
	if verb == "gc" {
		if len(args) > 0 && !(len(args) == 1 && args[0] == "--dry-run") {
			return commandhelp.Usage("run gc")
		}
		return ""
	}
	usage := "usage: ak run " + verb + " <runid>"
	budget := ""
	switch verb {
	case "status", "show":
		usage = commandhelp.Usage("run status") + " [--pending]"
		args = without(args, "--history", "--json", "--plain", "--why", "--pending")
		if len(args) > 1 || (len(args) == 1 && strings.HasPrefix(args[0], "-")) {
			return usage
		}
		if len(args) == 0 {
			return ""
		}
	case "stop":
		usage = commandhelp.Usage("run stop")
		args = without(args, "--keep")
	case "resume":
		usage += " [--rounds N] [--bg]"
		args = without(args, "--bg")
		if len(args) == 3 && args[1] == "--rounds" && positive(args[2]) {
			budget = rounds(args[2])
			args = args[:1]
		}
	}
	if len(args) != 1 || (verb != "status" && verb != "show" && !runID(args[0])) {
		return usage
	}
	if budget != "" {
		return budget
	}
	runs := filepath.Join(config.Home(), "runs")
	if !runID(args[0]) {
		return fmt.Sprintf("no such run: %s (looked in %s)", args[0], runs)
	}
	if verb == "status" || verb == "show" {
		data, _ := os.ReadFile(filepath.Join(config.Home(), "jobs", args[0], "job.json"))
		var job map[string]any
		if json.Unmarshal(data, &job) == nil {
			if _, ok := job["tasks"].([]any); ok {
				return ""
			}
		}
	}
	record := filepath.Join(runs, args[0], "run.json")
	data, err := os.ReadFile(record)
	if verb == "merge" {
		var state map[string]any
		if json.Unmarshal(data, &state) != nil || state["verdict"] != "PASS" || state["state"] != "pass" {
			return args[0] + ": merge requires a finished PASS"
		}
	} else if err != nil {
		if verb == "stop" && isFile(filepath.Join(config.Home(), "jobs", args[0], "job.json")) {
			return ""
		}
		if verb == "resume" {
			return fmt.Sprintf("no resumable run: %s (looked in %s)", args[0], runs)
		}
		return fmt.Sprintf("no such run: %s (looked in %s)", args[0], runs)
	}
	return ""
}
