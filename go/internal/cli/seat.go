package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"unicode"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

func validateNotify(args []string) string {
	if len(args) == 1 && args[0] == "--check" {
		return ""
	}
	if len(args) == 0 || args[0] != "needs" {
		return commandhelp.Usage("notify")
	}
	_, problem := parseNeeds(args[1:])
	return problem
}

// needs is `ak notify needs`'s words after `needs`; named is whether --session was given.
type needs struct {
	question, session string
	named, dryRun     bool
}

func parseNeeds(args []string) (needs, string) {
	var asked needs
	var rest []string
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--session":
			// for a caller that speaks for a seat it is not in: `ak watch` speaks for `inbox`
			if i+1 == len(args) {
				return asked, "--session needs a session name"
			}
			i++
			asked.session, asked.named = args[i], true
		case "--dry-run":
			asked.dryRun = true
		case "--file":
			return asked, "--file was removed: notification cards carry no attachments"
		default:
			rest = append(rest, args[i])
		}
	}
	if len(rest) != 1 || strings.HasPrefix(rest[0], "-") || config.Fold(rest[0]) == "" {
		return asked, commandhelp.Usage("notify")
	}
	asked.question = rest[0]
	return asked, ""
}

func validatePlan(args []string) string {
	name, record, err := config.CurrentSession()
	if err != nil {
		return err.Error()
	}
	if name == "" {
		return "ak plan belongs to a session; run it inside one"
	}
	if len(args) == 0 {
		return ""
	}
	if len(args) == 4 && args[0] == "add" && args[2] == "--check" {
		if config.Fold(args[1]) == "" || strings.Contains(args[1], "·") {
			return "an outcome is plain words without `·`"
		}
		repo, _ := record["repo"].(string)
		if _, err := os.Stat(filepath.Join(repo, ".git")); repo == "" || err != nil {
			return fmt.Sprintf("%s is filed under no project; run `ak orch project <checkout>` first", name)
		}
		if !oneCommand(args[3]) {
			return "a check is one shell command without backticks or line breaks"
		}
		return ""
	}
	if len(args) == 3 && args[0] == "check" && pythonDigits(args[1]) {
		if lineNumber(args[1]) && !oneCommand(args[2]) {
			return "a check is one shell command without backticks or line breaks"
		}
		return ""
	}
	return commandhelp.Usage("plan")
}

// pythonDigits is whether Python's isdigit may take text: each digit it takes is a decimal or
// other number.  runPlan leaves one that is no lineNumber (`٣`, `²`) to Python, which reads it.
func pythonDigits(text string) bool {
	return text != "" && !strings.ContainsFunc(text, func(r rune) bool { return !unicode.IsDigit(r) && !unicode.Is(unicode.No, r) })
}

// lineNumber is whether Go reads text as Python's int reads a plan line's number: ASCII digits,
// no more than the 640 every digit limit of Python's int takes (`PYTHONINTMAXSTRDIGITS`).
func lineNumber(text string) bool {
	return config.Digits(text) && len(text) <= 640
}
