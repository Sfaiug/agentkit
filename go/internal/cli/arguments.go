package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

func oneCommand(command string) bool {
	return len(config.SplitLines(strings.TrimFunc(command, config.Space))) == 1 && !strings.Contains(command, "`")
}

type arguments struct {
	values map[string]string
	flags  map[string]bool
	words  []string
}

func parse(args, values, flags []string, unknownUsage string) (arguments, string) {
	parsed := arguments{values: map[string]string{}, flags: map[string]bool{}}
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch {
		case contains(values, arg):
			if i+1 == len(args) {
				return parsed, arg + " needs a value"
			}
			i++
			parsed.values[arg] = args[i]
		case contains(flags, arg):
			parsed.flags[arg] = true
		case strings.HasPrefix(arg, "-"):
			return parsed, fmt.Sprintf("unknown flag %s; %s", commandhelp.Quote(arg), unknownUsage)
		default:
			parsed.words = append(parsed.words, arg)
		}
	}
	return parsed, ""
}

func positive(value string) bool {
	return config.Digits(value) && strings.TrimLeft(value, "0") != ""
}

func isFile(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

func isDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func runID(value string) bool {
	return value != "" && value != "." && value != ".." && filepath.Base(value) == value
}
