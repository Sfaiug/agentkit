package cli

import (
	"fmt"
	"os"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

const orchUsage = "usage: ak orch [name] [--model NAME] [--workers A,B] [--dry-run] | ak orch list [--why] | ak orch why NAME | ak orch stop <name> | ak orch rename [--auto] [OLD] NEW | ak orch project [<seat>] <checkout>"

func validateOrch(args []string) string {
	if len(args) > 0 {
		rest := args[1:]
		switch args[0] {
		case "list":
			if len(rest) > 0 && !(len(rest) == 1 && rest[0] == "--why") {
				return commandhelp.Usage("orch list")
			}
			return ""
		case "why", "rules", "stop":
			if len(rest) != 1 {
				if args[0] == "stop" {
					return "usage: ak orch stop <name>"
				}
				return commandhelp.Usage("orch " + args[0])
			}
			if args[0] == "rules" && os.Getenv("AGENTKIT_SESSION") == "" {
				return "ak orch rules belongs to a seat; run it inside one"
			}
			return ""
		case "rename", "project":
			verb := args[0]
			if verb == "rename" {
				rest = without(rest, "--auto")
			}
			if len(rest) < 1 || len(rest) > 2 {
				if verb == "project" {
					return "usage: ak orch project [<seat>] <checkout>"
				}
				return commandhelp.Usage("orch rename")
			}
			if len(rest) == 1 && os.Getenv("AGENTKIT_SESSION") == "" {
				if verb == "project" {
					return "ak orch project <checkout> files the session it runs in, and this is not one; use ak orch project <seat> <checkout>"
				}
				return "ak orch rename <new> renames the session it runs in, and this is not one; use ak orch rename <old> <new>"
			}
			if verb == "rename" && strings.HasPrefix(rest[len(rest)-1], "-") {
				return fmt.Sprintf("not a session name: %s", commandhelp.Quote(rest[len(rest)-1]))
			}
			return ""
		}
	}
	name := false
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch arg {
		case "--dry-run":
		case "--model", "--workers":
			if i+1 == len(args) {
				if arg == "--model" {
					return "--model needs a model name"
				}
				return "--workers needs a comma-separated list of model names"
			}
			i++
		default:
			if strings.HasPrefix(arg, "-") || name {
				return fmt.Sprintf("%s  (got %s)", orchUsage, commandhelp.Quote(arg))
			}
			name = true
		}
	}
	if err := config.Check(); err != nil {
		return err.Error()
	}
	return ""
}
