package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

func validateNotify(args []string) string {
	if len(args) == 1 && args[0] == "--check" {
		return ""
	}
	needs := len(args) > 0 && args[0] == "needs"
	session, dryRun := "", false
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
			session = args[i]
		} else if needs && arg == "--file" {
			return "--file was removed: notification cards carry no attachments"
		} else if needs && arg == "--dry-run" {
			dryRun = true
		} else {
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
		if !dryRun && session == "" && os.Getenv("AGENTKIT_SESSION") == "" {
			return "notify needs a session: use --session NAME"
		}
	}
	return ""
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
		if strings.TrimSpace(args[1]) == "" || strings.Contains(args[1], "·") {
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
	if len(args) == 3 && args[0] == "check" && digits(args[1]) {
		if !oneCommand(args[2]) {
			return "a check is one shell command without backticks or line breaks"
		}
		return ""
	}
	return commandhelp.Usage("plan")
}
