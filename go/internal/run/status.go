package run

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"

	"agentkit/internal/config"
)

// Models is today's config's models, none where it cannot be read.
func Models() map[string]config.Model {
	models, err := config.Models()
	if err != nil {
		return nil
	}
	return models
}

func sameModel(models map[string]config.Model, first, second string) bool {
	if first == "" || second == "" {
		return false
	}
	if first == second {
		return true
	}
	one, ok := models[first]
	two, found := models[second]
	return ok && found && one == two
}

// SelfReviewed is whether the executor's own model reviews the run: the recorded review's
// pair where a round was reviewed, else the current one.  A seat's own PR has no executor,
// so its orchestrator counts as one.
func SelfReviewed(record *Object, models map[string]config.Model) bool {
	evidence := record.Dict("review")
	if evidence == nil {
		evidence = NewObject()
	}
	reviewer := evidence.Get("reviewer")
	if !truthy(reviewer) {
		reviewer = record.Get("reviewer")
	}
	executor := evidence.Get("executor")
	if executor == nil {
		executor = record.Get("executor")
		if record.Truthy("own_pr") {
			executor = record.Get("own_orchestrator")
		}
	}
	if !truthy(reviewer) || !truthy(executor) || equal(reviewer, executor) {
		return truthy(reviewer) && equal(reviewer, executor)
	}
	first, _ := executor.(string)
	second, _ := reviewer.(string)
	return sameModel(models, first, second)
}

// ExecutorLine is who executed: `astra → opus (ran dry)` where the work changed hands.
func ExecutorLine(record *Object) string {
	name := Field(record, "executor", "?")
	var held []*Object
	for _, entry := range record.List("executor_history") {
		if link, ok := entry.(*Object); ok && (link.Get("from") == nil || link.Get("to") == nil || !equal(link.Get("from"), link.Get("to"))) {
			held = append(held, link)
		}
	}
	if len(held) == 0 {
		return name
	}
	var chain []string
	for _, link := range held {
		chain = append(chain, firstText(link, "?", "model", "from"))
	}
	chain = append(chain, name)
	return strings.Join(chain, " → ") + " (" + firstText(held[len(held)-1], "changed", "why", "reason") + ")"
}

func zero(value any) bool {
	if value == false {
		return true
	}
	parsed, ok := Num(value)
	return ok && parsed == 0
}

// providers is the (executor, reviewer) providers, or false where a name is no model.
func providers(models map[string]config.Model, executor any, reviewer string) (executed, reviewed any, ok bool) {
	if truthy(executor) {
		name, _ := executor.(string)
		model, ok := models[name]
		if !ok {
			return nil, nil, false
		}
		executed = model.Provider
	}
	model, ok := models[reviewer]
	return executed, model.Provider, ok
}

// ReviewPass is whether the record holds evidence of a successful review, not a verdict alone.
func ReviewPass(record *Object, models map[string]config.Model) bool {
	evidence := record.Dict("review")
	if record.Str("verdict") != "PASS" || evidence == nil {
		return false
	}
	if record.Truthy("repo") && !(evidence.Truthy("head_sha") && evidence.Truthy("tree_sha")) {
		return false
	}
	checked := evidence.Get("done_when") == true || record.Truthy("review_pr") && evidence.Has("done_when") && evidence.Get("done_when") == nil
	if !zero(evidence.Get("returncode")) || evidence.Str("verdict") != "PASS" || !checked ||
		!equal(evidence.Get("executor"), record.Get("executor")) || !evidence.Truthy("reviewer") ||
		!equal(evidence.Get("reviewer"), record.Get("reviewer")) || !evidence.Truthy("reviewer_provider") {
		return false
	}
	if !record.Truthy("executor") {
		if !record.Truthy("review_pr") || evidence.Get("executor_provider") != nil {
			return false
		}
	} else if !evidence.Truthy("executor_provider") {
		return false
	}
	executed, reviewed, ok := providers(models, record.Get("executor"), record.Str("reviewer"))
	if !ok || !equal(executed, evidence.Get("executor_provider")) || !equal(reviewed, evidence.Get("reviewer_provider")) {
		return false
	}
	if record.Truthy("own_pr") {
		if !record.Truthy("own_orchestrator") {
			return false
		}
		if _, _, ok := providers(models, record.Get("own_orchestrator"), record.Str("reviewer")); !ok {
			return false
		}
	}
	return true
}

// Delivery is the review verdict and the delivery outcome: `PASS, merged`, `FAIL`, ...
func Delivery(record *Object, models map[string]config.Model) string {
	switch record.Str("state") {
	case "not_needed":
		return "not needed: " + Field(record, "not_needed", "None")
	case "waiting":
		return "WAITING: " + firstText(record, "delivery pending", "merge_note", "error")
	case "error", "fail", "interrupted", "exhausted", "blocked", "waiting_login", "stopped":
		return "FAIL"
	}
	switch {
	case !ReviewPass(record, models):
		return "FAIL"
	case record.Truthy("scratch"):
		return "PASS, delivered"
	case record.Truthy("merged"):
		return "PASS, merged"
	}
	reason := "delivery did not finish"
	if record.Truthy("review_pr") {
		reason = "review only"
	} else if record.Truthy("no_merge") {
		reason = "--no-merge"
	}
	return "PASS, not merged: " + firstText(record, reason, "merge_note")
}

// Outcome is what became of a finished run's work, its verdict aside.
func Outcome(record *Object, models map[string]config.Model) string {
	switch {
	case !record.Truthy("finished_at"):
		return ""
	case record.Truthy("merged"):
		return "merged"
	case record.Truthy("pr"):
		return "PR open"
	}
	word := Delivery(record, models)
	if rest, ok := strings.CutPrefix(word, "PASS, "); ok {
		return rest
	}
	return ""
}

// StepWord is the step a running run is in and for how long: `executor 41m`.
func StepWord(record *Object, now time.Time) string {
	if record.Str("state") != "running" || !record.Truthy("step") {
		return ""
	}
	at, ok := record.Num("step_at")
	if _, isBool := record.Get("step_at").(bool); !ok || isBool {
		return Text(record.Get("step"))
	}
	return Text(record.Get("step")) + " " + span(seconds(now)-at)
}

// span is a length of time in the one unit that says the most about it: `2d`, `3h`, `45s`.
func span(elapsed float64) string {
	secs := int64(max(0, elapsed))
	for _, unit := range []struct {
		name string
		size int64
	}{{"d", 86400}, {"h", 3600}, {"m", 60}} {
		if secs >= unit.size {
			return strconv.FormatInt(secs/unit.size, 10) + unit.name
		}
	}
	return strconv.FormatInt(secs, 10) + "s"
}

var (
	doneWhen = regexp.MustCompile(`(?ims)^##\s+Done when\s*$(.*?)(?:^##\s|\z)`)
	fence    = regexp.MustCompile("(?s)```(?:bash|sh)?\n(.*?)```")
	frontRe  = regexp.MustCompile(`(?s)^---\n(.*?)\n---\n?(.*)$`)
	agentsRe = regexp.MustCompile(`(?s)^---\n(|.*?\n)---`)
	onceRe   = regexp.MustCompile(`^#\s*once\s*$`)
)

var taskKeys = []string{"after", "base", "done_when_minutes", "files", "from", "merge", "repo",
	"rounds", "stall_minutes", "target", "turn_hours"}

// doneWhenCommands is the task's done-when commands, or false where the task is unreadable.
func doneWhenCommands(path string) ([]string, bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, false
	}
	text := universal(data)
	body := text
	if match := frontRe.FindStringSubmatch(text); match != nil {
		for _, line := range strings.Split(match[1], "\n") {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			key, _, found := strings.Cut(line, ":")
			if !found || !slices.Contains(taskKeys, strings.TrimSpace(key)) {
				return nil, false
			}
		}
		body = match[2]
	} else if strings.HasPrefix(text, "---\n") {
		return nil, false
	}
	section := doneWhen.FindStringSubmatch(body)
	if section == nil {
		return nil, false
	}
	block := fence.FindStringSubmatch(section[1])
	if block == nil {
		return nil, false
	}
	var cmds []string
	for _, line := range strings.Split(block[1], "\n") {
		if line = strings.TrimSpace(line); line != "" && !strings.HasPrefix(line, "#") {
			cmds = append(cmds, line)
		}
	}
	return cmds, len(cmds) > 0
}

// once is whether a command ends in a `# once` marker outside any quotes.
func once(cmd string) bool {
	single, double, escaped := false, false, false
	for i, ch := range cmd {
		switch {
		case escaped:
			escaped = false
		case ch == '\\' && !single:
			escaped = true
		case ch == '\'' && !double:
			single = !single
		case ch == '"' && !single:
			double = !double
		case ch == '#' && !single && !double:
			if i > 0 && (cmd[i-1] == ' ' || cmd[i-1] == '\t') && onceRe.MatchString(cmd[i:]) {
				return true
			}
		}
	}
	return false
}

// frontValue is a key's value in AGENTS.md front matter, or "".
func frontValue(text, key string) string {
	match := agentsRe.FindStringSubmatch(text)
	if match == nil {
		return ""
	}
	for _, line := range strings.Split(match[1], "\n") {
		name, value, found := strings.Cut(strings.TrimSpace(line), ":")
		if found && strings.TrimSpace(name) == key && strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

// declaredSuite is the target's `tests:` suite at `origin/<target>`, else the checkout's.
func declaredSuite(worktree, target string) string {
	if target != "" {
		ref := target
		if !strings.HasPrefix(ref, "origin/") {
			ref = "origin/" + target
		}
		command := exec.Command("git", "-C", worktree, "show", ref+":AGENTS.md")
		command.Env = append(os.Environ(), "GIT_TERMINAL_PROMPT=0")
		if out, err := command.Output(); err == nil || errors.As(err, new(*exec.ExitError)) {
			if suite := frontValue(strings.TrimSpace(universal(out)), "tests"); suite != "" {
				return suite
			}
		}
	}
	data, err := os.ReadFile(filepath.Join(worktree, "AGENTS.md"))
	if err != nil {
		return ""
	}
	return frontValue(universal(data), "tests")
}

// universal is text as Python reads a text file or a command's output: every line ending a
// newline.
func universal(data []byte) string {
	return strings.NewReplacer("\r\n", "\n", "\r", "\n").Replace(string(data))
}

// FinalCheck is the run's `final check:` line, or "" where its task cannot be read.
func FinalCheck(dir string, record *Object) string {
	cmds, ok := doneWhenCommands(filepath.Join(dir, "task.md"))
	if !ok {
		return ""
	}
	if check := record.Dict("final_check"); check != nil {
		outcome := check.Str("outcome")
		where := check.Str("where")
		if (outcome == "passed" || outcome == "failed") && (check.Truthy("sha") || where == "round" || where == "landing") {
			sha := ""
			if check.Truthy("sha") {
				sha = " on " + Text(check.Get("sha"))
			}
			switch {
			case where == "round" && check.Truthy("round"):
				return "final check: " + outcome + " in round " + Text(check.Get("round")) + sha
			case where == "round":
				return "final check: " + outcome + " in round" + sha
			case where == "landing" && check.Truthy("tested") && !equal(check.Get("tested"), check.Get("tree_sha")):
				return "final check: " + outcome + " at landing on tree " + Text(check.Get("tested"))
			case where == "landing":
				return "final check: " + outcome + " at landing" + sha
			}
			return "final check: " + outcome + sha
		}
	}
	landing := !record.Truthy("scratch") && !record.Truthy("no_merge")
	any := false
	for _, cmd := range cmds {
		any = any || once(cmd)
	}
	if landing && !any && !record.Truthy("review_pr") && worktree(record) != "" {
		target := record.Str("target")
		if !record.Truthy("target") {
			target = record.Str("base")
		}
		any = declaredSuite(worktree(record), target) != ""
	}
	if landing && any {
		return "final check: not run"
	}
	return "final check: none (no once-commands)"
}

// realpath resolves what exists of a path and keeps the rest as written, as Python's does.
func realpath(path string) string {
	path, rest := filepath.Clean(path), ""
	for {
		if resolved, err := filepath.EvalSymlinks(path); err == nil {
			return filepath.Join(resolved, rest)
		}
		parent := filepath.Dir(path)
		if parent == path {
			return filepath.Join(path, rest)
		}
		rest = filepath.Join(filepath.Base(path), rest)
		path = parent
	}
}

func looped(path string) bool {
	_, err := os.Stat(path)
	return errors.Is(err, syscall.ELOOP)
}

// SmokeRun is a run of the smoke suite, whose task or repository lives in its sandbox.
func SmokeRun(record *Object) bool {
	sandbox := realpath(filepath.Join(config.Home(), "tmp")) + string(filepath.Separator)
	for _, key := range []string{"task", "repo"} {
		value := record.Str(key)
		if value == "" {
			continue
		}
		path := config.Expand(value)
		real := realpath(path)
		if strings.HasPrefix(real, sandbox) && strings.HasPrefix(real[len(sandbox):], "smoke-") &&
			!looped(path) && !looped(real) {
			return true
		}
	}
	return false
}
