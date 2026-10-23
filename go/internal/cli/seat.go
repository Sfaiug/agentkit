package cli

import (
	"bufio"
	"encoding/json"
	"os"
	"strings"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
)

func validateNotify(args []string) string {
	if len(args) == 1 && args[0] == "--check" {
		return ""
	}
	needs := len(args) > 0 && args[0] == "needs"
	var rest []string
	start := 0
	if needs {
		start = 1
	}
	for i := start; i < len(args); i++ {
		arg := args[i]
		if needs && arg == "--session" {
			if i+1 == len(args) {
				return "--session needs a session name"
			}
			i++
		} else if needs && arg == "--file" {
			return "--file was removed: notification cards carry no attachments"
		} else if !needs || arg != "--dry-run" {
			rest = append(rest, arg)
		}
	}
	if !needs || len(rest) != 1 || strings.HasPrefix(rest[0], "-") || strings.TrimSpace(rest[0]) == "" {
		return commandhelp.Usage("notify")
	}
	if os.Getenv("AK_RUN_ROLE") != "worker" {
		asked, _, found := strings.Cut(strings.Join(strings.Fields(rest[0]), " "), "?")
		if !found || utf8.RuneCountInString(asked) >= 80 {
			return `put the question first, its "?" within 80 characters: the status bar and the menu show a question's start; context goes after it`
		}
	}
	return ""
}

func validatePlan(args []string) string {
	if os.Getenv("AGENTKIT_SESSION") == "" {
		return "ak plan belongs to a session; run it inside one"
	}
	if len(args) == 0 || (len(args) == 4 && args[0] == "add" && args[2] == "--check") || (len(args) == 3 && args[0] == "check" && digits(args[1])) {
		return ""
	}
	return commandhelp.Usage("plan")
}

func validateHandIn(args []string) string {
	path := os.Getenv("AK_HAND_IN")
	if path == "" || !isFile(path) {
		return "hand-in needs an active worker turn; use it from the worker's shell"
	}
	file, err := os.Open(path)
	if err != nil {
		return "cannot hand in this record: " + err.Error()
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	scanner.Buffer(nil, int(^uint(0)>>1))
	var turn struct {
		Kind string `json:"kind"`
		Role string `json:"role"`
	}
	if !scanner.Scan() {
		if err := scanner.Err(); err != nil {
			return "cannot hand in this record: " + err.Error()
		}
		return "the worker turn's record file is invalid; ask the loop to retry"
	}
	if err := json.Unmarshal(scanner.Bytes(), &turn); err != nil {
		return "cannot hand in this record: " + err.Error()
	}
	if turn.Kind != "turn" {
		return "the worker turn's record file is invalid; ask the loop to retry"
	}
	for scanner.Scan() {
		var row struct {
			Kind string `json:"kind"`
		}
		if err := json.Unmarshal(scanner.Bytes(), &row); err != nil {
			return "cannot hand in this record: " + err.Error()
		}
		if contains([]string{"done", "blocked", "not-needed"}, row.Kind) {
			return "this turn is already closed; hand in records before done, blocked or not-needed"
		}
	}
	if err := scanner.Err(); err != nil {
		return "cannot hand in this record: " + err.Error()
	}
	if turn.Role == "" {
		turn.Role = "reviewer"
	}
	if len(args) > 0 {
		switch args[0] {
		case "blocked", "not-needed":
			if strings.HasPrefix(turn.Role, "reviewer") {
				return "blocked and not-needed are only for executor or fixer turns"
			}
			if len(args) != 2 || strings.TrimSpace(args[1]) == "" {
				return `use blocked or not-needed with one nonempty "why"`
			}
			return ""
		case "finding", "follow-up":
			if !strings.HasPrefix(turn.Role, "reviewer") {
				return "finding and follow-up are only for review turns"
			}
		case "dispute":
			if !strings.HasPrefix(turn.Role, "fixer") {
				return "dispute is only for fixer turns"
			}
			if len(args) < 3 || strings.TrimSpace(args[2]) == "" {
				return `use dispute with path:line, "why it is wrong" and evidence`
			}
			return ""
		}
	}
	if len(args) == 1 && args[0] == "done" {
		return ""
	}
	if len(args) < 4 || !contains([]string{"finding", "follow-up"}, args[0]) {
		return "use finding or follow-up with path:line, what, why it matters and evidence, dispute, or done alone"
	}
	if strings.TrimSpace(args[2]) == "" || strings.TrimSpace(args[3]) == "" {
		return "supply both what is wrong and why it matters"
	}
	flags := map[string]string{}
	for i := 4; i < len(args); i += 2 {
		_, duplicate := flags[args[i]]
		if !contains([]string{"--run", "--quote", "--before"}, args[i]) || duplicate || i+1 == len(args) {
			return "use one evidence flag, --run COMMAND or --quote LINES, and --before PROOF for a follow-up that predates the task"
		}
		flags[args[i]] = args[i+1]
	}
	_, run := flags["--run"]
	_, quote := flags["--quote"]
	if run == quote || strings.TrimSpace(flags["--run"]+flags["--quote"]) == "" {
		return "supply evidence with exactly one of --run COMMAND or --quote LINES"
	}
	before, hasBefore := flags["--before"]
	if args[0] == "follow-up" {
		if hasBefore && strings.TrimSpace(before) == "" {
			return "--before names the base or an ancestor commit, or verbatim lines from the named file at base"
		}
		if !hasBefore && !run {
			return "a follow-up without --before needs --run: its command becomes the check that fixes it"
		}
	} else if hasBefore {
		return "use follow-up for a defect that existed before the task"
	}
	return ""
}
