package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"agentkit/internal/commandhelp"
)

var lineBreak = regexp.MustCompile(`\r\n|[\n\r\v\f\x1c-\x1e\x{85}\x{2028}\x{2029}]`)

func splitLines(text string) []string {
	if text == "" {
		return nil
	}
	lines := lineBreak.Split(text, -1)
	if lines[len(lines)-1] == "" {
		lines = lines[:len(lines)-1]
	}
	return lines
}

func oneCommand(command string) bool {
	return len(splitLines(strings.TrimSpace(command))) == 1 && !strings.Contains(command, "`")
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

func digits(value string) bool {
	if value == "" {
		return false
	}
	for _, r := range value {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func positive(value string) bool {
	return digits(value) && strings.TrimLeft(value, "0") != ""
}

func rounds(value string) string {
	trimmed := strings.TrimLeft(value, "0")
	if digits(value) && (len(trimmed) > 1 || trimmed > "3") {
		return fmt.Sprintf("--rounds %s is over the budget: 3 rounds, then a run goes back to its orchestrator to split or re-scope", trimmed)
	}
	return ""
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
