// Package cli owns dispatch and argument validation. Operations stay in shadow until
// their Go implementations pass the answer key; an unimplemented call never launches a tool.
package cli

import (
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/fetch"
	"agentkit/internal/terminal"
)

func Main(args []string, out, errOut io.Writer) int {
	command, rest, help := "attach", args, ""
	if len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		command, rest, help = args[0], args[1:], args[0]
	}
	if !contains(commandhelp.Verbs, command) {
		fmt.Fprintf(errOut, "ak: unknown subcommand %s; expected one of %s\n", commandhelp.Quote(command), strings.Join(commandhelp.Verbs, ", "))
		return 2
	}
	if entry, ok := commandhelp.Help(help, rest); ok {
		fmt.Fprint(out, commandhelp.Render(entry, func(text string) string { return terminal.Dim(out, text) }))
		return 0
	}
	if command == "browser" && len(rest) == 0 {
		fmt.Fprint(out, commandhelp.Render("browser", func(text string) string { return text }))
		return 2
	}
	if command == "run" && (!runSubcommand(rest) || rest[0] == "resume") {
		raw := os.Getenv("AK_RUN_DEPTH")
		if _, set := os.LookupEnv("AK_RUN_DEPTH"); !set {
			raw = "0"
		}
		if !digits(raw) {
			fmt.Fprintln(errOut, "ak run: AK_RUN_DEPTH must be a non-negative integer")
			return 2
		}
		depth, err := strconv.ParseUint(raw, 10, 64)
		if err != nil || depth >= 2 {
			shown := strings.TrimLeft(raw, "0")
			fmt.Fprintf(errOut, "a worker's worker may not start runs (depth %s); only the orchestrator, and a worker for its tests, may\n", shown)
			return 2
		}
	}
	if problem := validate(command, rest); problem != "" {
		fmt.Fprintf(errOut, "ak %s: %s\n", command, problem)
		return 2
	}
	if command == "wait" && os.Getenv("AGENTKIT_SESSION") == "" {
		fmt.Fprintln(errOut, "ak wait: no seat: run it inside an orchestrator session")
		return 1
	}
	if command == "fetch" {
		result := fetch.Local(rest)
		if !result.Pending || len(result.Errors) > 0 {
			for _, path := range result.Paths {
				fmt.Fprintln(out, path)
			}
			for _, problem := range result.Errors {
				fmt.Fprintln(errOut, "ak fetch: "+problem)
			}
			if len(result.Errors) > 0 {
				return 1
			}
			return 0
		}
	}
	// These commands read configuration before their first operation. Help and
	// argument refusals above must remain usable even when that file is broken.
	if command == "usage" || command == "models" {
		if err := config.Check(); err != nil {
			fmt.Fprintf(errOut, "ak %s: %s\n", command, err)
			return 2
		}
	}
	if len(rest) > 0 && commandhelp.Known(command+" "+rest[0]) {
		command += " " + rest[0]
	}
	fmt.Fprintf(errOut, "ak %s: not implemented in Go yet\n", command)
	return 3
}

func reprList(args []string) string {
	values := make([]string, len(args))
	for i, arg := range args {
		values[i] = commandhelp.Quote(arg)
	}
	return "[" + strings.Join(values, ", ") + "]"
}

func contains(args []string, wanted string) bool {
	for _, arg := range args {
		if arg == wanted {
			return true
		}
	}
	return false
}

func without(args []string, flags ...string) []string {
	var rest []string
	for _, arg := range args {
		if !contains(flags, arg) {
			rest = append(rest, arg)
		}
	}
	return rest
}
