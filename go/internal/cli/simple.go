package cli

import (
	"fmt"
	"runtime"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/fetch"
)

const menuUsage = "usage: ak [--client] [--overlay] [--dry-run]   (the menu; `ak attach` is the same)"

func validate(command string, args []string) string {
	usage := commandhelp.Usage(command)
	switch command {
	case "usage", "models", "attach", "doctor":
		allowed := map[string][]string{
			"usage": {"--json"}, "models": {"--json", "--refresh"},
			"attach": {"--client", "--overlay", "--dry-run"},
		}
		for _, arg := range args {
			if !contains(allowed[command], arg) {
				if command == "models" {
					return fmt.Sprintf("%s  (got %s)", usage, reprList(args))
				}
				if command == "attach" {
					usage = menuUsage
				}
				return fmt.Sprintf("%s  (got %s)", usage, commandhelp.Quote(arg))
			}
		}
	case "update", "watch":
		if len(args) > 0 && !(len(args) == 1 && args[0] == "--dry-run") {
			return fmt.Sprintf("%s  (got %s)", usage, commandhelp.Quote(args[0]))
		}
	case "macbridge":
		if runtime.GOOS != "darwin" {
			return "ak macbridge runs on macOS; use ak fetch on this host"
		}
		if len(args) > 0 && !(len(args) == 1 && args[0] == "--reader") {
			return usage
		}
	case "fetch":
		return fetch.Validate(args)
	case "wait":
		if len(args) != 1 || strings.HasPrefix(args[0], "-") {
			return usage
		}
	case "browser":
		if !commandhelp.Known("browser " + args[0]) {
			return fmt.Sprintf("unknown command %s; expected one of status, login, mcp-register, install", commandhelp.Quote(args[0]))
		}
		if len(args) > 1 {
			return fmt.Sprintf("ak browser %s takes no arguments; got %s", args[0], strings.Join(args[1:], " "))
		}
	case "worker":
		return validateWorker(args)
	case "run":
		return validateRun(args)
	case "orch":
		return validateOrch(args)
	case "notify":
		return validateNotify(args)
	case "plan":
		return validatePlan(args)
	}
	return ""
}
