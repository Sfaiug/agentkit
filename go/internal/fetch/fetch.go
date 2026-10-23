// Package fetch resolves local files without starting the Mac bridge.
package fetch

import (
	"math"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"unicode"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

var decimal = regexp.MustCompile(`^[+-]?(?:[0-9](?:_?[0-9])*(?:\.(?:[0-9](?:_?[0-9])*)?)?|\.[0-9](?:_?[0-9])*)(?:[eE][+-]?[0-9](?:_?[0-9])*)?$`)

const invalidPath = "a file path must be non-empty and contain no tabs or newlines"

func Validate(args []string) string {
	if len(args) == 1 && args[0] == "--serve" {
		return ""
	}
	if len(args) > 0 && args[0] == "--" {
		args = args[1:]
	}
	if len(args) == 0 {
		return commandhelp.Usage("fetch")
	}
	for _, arg := range args {
		if arg == "--serve" {
			return commandhelp.Usage("fetch")
		}
	}
	if raw, ok := os.LookupEnv("AK_FETCH_TIMEOUT"); ok {
		raw = strings.TrimSpace(raw)
		value, err := strconv.ParseFloat(raw, 64)
		if !decimal.MatchString(raw) || err != nil || math.IsNaN(value) || math.IsInf(value, 0) || value < 0 {
			return "AK_FETCH_TIMEOUT must be a finite, non-negative number"
		}
	}
	return ""
}

func normalize(value string) (string, string) {
	if value == "" || strings.ContainsAny(value, "\x00\r\n\t") {
		return "", invalidPath
	}
	if _, err := os.Stat(config.Expand(value)); err == nil {
		return config.Expand(value), ""
	}
	value = strings.TrimSpace(value)
	if len(value) > 1 && value[0] == value[len(value)-1] && (value[0] == '\'' || value[0] == '"') {
		value = value[1 : len(value)-1]
	}
	// Terminal and Finder escape punctuation when a path is dropped into a shell.
	runes := []rune(value)
	var out strings.Builder
	for i := 0; i < len(runes); i++ {
		if runes[i] == '\\' && i+1 < len(runes) && (unicode.IsSpace(runes[i+1]) || strings.ContainsRune("\\'\"()[]{}<>|;&!$`*?#~", runes[i+1])) {
			i++
		}
		out.WriteRune(runes[i])
	}
	value = out.String()
	if value == "" || strings.ContainsAny(value, "\x00\r\n\t") {
		return "", invalidPath
	}
	return value, ""
}

type Result struct {
	Paths, Errors []string
	Pending       bool
}

func Local(args []string) Result {
	result := Result{}
	if len(args) == 0 || (len(args) == 1 && args[0] == "--serve") {
		result.Pending = true
		return result
	}
	if args[0] == "--" {
		args = args[1:]
	}
	for _, arg := range args {
		path, problem := normalize(arg)
		if problem != "" {
			result.Errors = append(result.Errors, problem)
			continue
		}
		path = config.Expand(path)
		if _, err := os.Stat(path); err != nil {
			result.Pending = true
			continue
		}
		absolute, err := filepath.Abs(path)
		if err != nil {
			result.Errors = append(result.Errors, err.Error())
			continue
		}
		result.Paths = append(result.Paths, absolute)
	}
	return result
}
